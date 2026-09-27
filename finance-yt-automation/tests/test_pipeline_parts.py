from finance_channel.captions import build_ass, chunk_words
from finance_channel.demo import demo_plan
from finance_channel.jobs import Job, JobStore
from finance_channel.producer import build_description, compute_facts
from finance_channel.render import RenderedScene, build_chapters
from finance_channel.schemas import VideoMetadata
from finance_channel.topics import Topic, TopicQueue
from pipeline import _parse_interval


def test_parse_interval():
    assert _parse_interval("24h") == 86400
    assert _parse_interval("90m") == 5400
    assert _parse_interval("2d") == 172800
    assert _parse_interval("3600") == 3600


def test_topic_queue_pillars_and_idempotence(tmp_path):
    tf = tmp_path / "topics.txt"
    tf.write_text("# comment\nsaving | emergency funds 101\nplain topic\n")
    q = TopicQueue(tf, tmp_path)
    assert [t.text for t in q.pending()] == ["emergency funds 101", "plain topic"]
    assert q.pending()[0].pillar == "saving"
    q.mark_done(q.pending()[0])
    assert [t.text for t in TopicQueue(tf, tmp_path).pending()] == ["plain topic"]
    added = q.append([Topic("plain topic"), Topic("new one", "debt"), Topic("Emergency Funds 101")])
    assert [t.text for t in added] == ["new one"]
    assert "debt | new one" in tf.read_text()


def test_chunk_words_breaks_on_punctuation():
    words = [{"start": i, "end": i + 0.5, "word": w}
             for i, w in enumerate("One two. Three four five six seven".split())]
    chunks = chunk_words(words, 4)
    assert [c[2] for c in chunks] == ["One two.", "Three four five six", "seven"]
    assert chunks[0][1] == chunks[1][0]   # held until the next caption


def test_build_ass_uses_video_canvas(tmp_path, config):
    words = [{"start": 0, "end": 0.4, "word": "Hello"}, {"start": 0.4, "end": 0.8, "word": "{there}"}]
    ass = build_ass(words, tmp_path / "c.ass", config=config, width=1080, height=1920, position="bottom")
    text = ass.read_text()
    assert "PlayResX: 1080" in text and "PlayResY: 1920" in text
    assert "Hello (there)" in text


def test_chapters_merge_and_fold():
    scenes = [RenderedScene(0, "Intro", 0, 12, None), RenderedScene(1, "The math", 12, 6, None),
              RenderedScene(2, "The math", 18, 8, None), RenderedScene(3, "Oops", 26, 3, None),
              RenderedScene(4, "Takeaway", 29, 15, None)]
    chapters = build_chapters(scenes)
    assert chapters == [(0.0, "Intro"), (12, "The math"), (29, "Takeaway")]
    assert build_chapters(scenes[:2]) == []


def test_demo_plan_computes_facts():
    facts, problems = compute_facts(demo_plan(), "$")
    assert not problems and "$243,994" in facts[0]


def test_description_includes_disclaimers_and_chapters(config):
    meta = VideoMetadata(title="t", description="Learn X.", tags=[], hashtags=["money"])
    desc = build_description(meta, config, [(0, "Intro"), (75, "Math"), (200, "End")])
    assert desc.startswith("Learn X.")
    assert "0:00 Intro" in desc and "1:15 Math" in desc
    assert "not financial" in desc and "#money" in desc


def test_job_store_roundtrip_and_latest_skips_blocked(tmp_path):
    store = JobStore(tmp_path)
    a = Job(id=store.new_id("short"), video_format="short", video_path="a.mp4")
    store.save(a)
    b = Job(id=store.new_id("short"), video_format="short", video_path="b.mp4", review_status="blocked")
    store.save(b)
    assert a.id != b.id
    assert store.latest(not_uploaded=True).video_path == "a.mp4"
    assert store.load(a.id).video_path == "a.mp4"


class StubLLM:
    """Stands in for the Claude client in plan_and_review."""

    def __init__(self, bad_text, fixed_text=None, n_issues=0):
        self.bad_text, self.fixed_text = bad_text, fixed_text

    def plan_video(self, topic, *, video_format, pillar=""):
        plan = demo_plan()
        plan.scenes[0].narration = self.bad_text
        return plan

    def review_script(self, plan, *, computed_facts, scanner_findings):
        from finance_channel.schemas import ScriptReview

        self.seen_findings = scanner_findings
        self.seen_facts = computed_facts
        narr = [s.narration for s in plan.scenes]
        if self.fixed_text:
            narr[0] = self.fixed_text
        return ScriptReview(issues=[], revised_narrations=narr, fact_check=["check 7%"], summary="ok")


def test_plan_and_review_blocks_unfixed_violation(config):
    from finance_channel.producer import ComplianceBlocked, plan_and_review, produce

    stub = StubLLM("Index funds give guaranteed returns of 10% a year.")
    reviewed = plan_and_review("t", pillar="", video_format="short", config=config, llm=stub)
    assert reviewed.status == "blocked"
    assert any("guaranteed-returns" in f for f in stub.seen_findings)
    assert any("$243,994" in f for f in stub.seen_facts)
    import pytest
    with pytest.raises(ComplianceBlocked):
        produce(reviewed, config=config, store=JobStore(config.workdir), llm=None)


def test_plan_and_review_accepts_fix_and_adds_disclaimer(config):
    from finance_channel.producer import plan_and_review

    stub = StubLLM("Index funds give guaranteed returns of 10% a year.",
                   fixed_text="Historically, index funds have averaged around 10% a year, "
                              "though returns are never guaranteed.")
    reviewed = plan_and_review("t", pillar="", video_format="short", config=config, llm=stub)
    assert reviewed.status == "approved"
    assert reviewed.plan.scenes[-1].narration.endswith("not financial advice.")
    assert reviewed.review.fact_check == ["check 7%"]
