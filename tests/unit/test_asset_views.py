"""FR-06, rule 5/6: generated camera views keep a recipe, a fidelity check and a disclosure."""

import base64

import pytest
import pytest_socket
from fastapi.testclient import TestClient

from instabay.assets.classify import fidelity_questions
from instabay.assets.export import export_library
from instabay.assets.library import AssetLibrary
from instabay.assets.variants import StubViewBackend, make_view, view_recipe
from instabay.content.photos import PhotoRecipe, PhotoStudio
from instabay.dashboard.app import create_app
from instabay.decisions.vision import FakeVisionEngine, VisionFixture, vision_key
from instabay.video.keyframes import runtime_identity
from tests.support import demo_brand
from tests.unit.test_assets import PILLARS, jpeg, owner_photo


@pytest.fixture
def library(tmp_path):
    with AssetLibrary(tmp_path / "ws", root=tmp_path) as lib:
        yield lib


def judge_for(library, parent, view_bytes_path):
    state = "Original resort photograph, then a generated camera view of it."
    s, q, shas = vision_key(state, fidelity_questions(), [library.path(parent), view_bytes_path])
    return FakeVisionEngine(
        [
            VisionFixture(
                state_hash=s,
                questions_hash=q,
                images_sha256=shas,
                response={"answers": {"same_place": {"noul": 0.88}, "photoreal": {"noul": 0.93}}},
            )
        ]
    )


def test_view_stores_recipe_inherits_pillar_records_fidelity_and_dedupes(library, tmp_path):
    parent = owner_photo(library, 5, "local")
    backend = StubViewBackend()
    recipe = view_recipe(parent, "aerial", 3, "rev1")
    preview = tmp_path / "preview.png"
    preview.write_bytes(backend.render([library.path(parent).read_bytes()], recipe))
    view = make_view(
        library,
        parent,
        "aerial",
        3,
        backend=backend,
        revision="rev1",
        judge=judge_for(library, parent, preview),
    )
    assert view.origin == "generated" and view.parent_id == parent.id
    assert view.recipe and view.recipe["recipe_hash"] == recipe.hash
    assert view.recipe["backend"] == "stub-view-v1" and "Do not add" in view.recipe["prompt"]
    assert view.pillar == "local" and not view.usable
    assert view.fidelity == {
        "engine": "fake-d3-flash-v1",
        "synthetic": True,
        "same_place": 0.88,
        "photoreal": 0.93,
    }
    again = make_view(library, parent, "aerial", 3, backend=backend, revision="rev1")
    assert again.id == view.id and len(library.all()) == 2
    with pytest.raises(ValueError, match="real photos"):
        make_view(library, view, "aerial", 3, backend=backend, revision="rev1")
    assert (recipe.width, recipe.height) == (1808, 1360)
    with pytest.raises(ValueError, match="Unknown camera"):
        view_recipe(parent, "cartoon", 1, "rev1")


def test_generated_photo_post_requires_ai_disclosure(library):
    parent = library.add(
        jpeg((40, 90, 160), (1200, 1500)),
        added_by="owner",
        rights_confirmed=True,
        note_en="Sea view",
        note_ar="منظر البحر",
    )
    parent = library.review(parent.id, owner_pillar="spa")
    view = make_view(library, parent, "guests", 1, backend=StubViewBackend(), revision="r")
    library.review(view.id, approved=True)
    for index, pillar in enumerate(PILLARS):
        owner_photo(library, 20 + index, pillar)
    _, catalog = export_library(library, demo_brand(), library.workspace / "export")
    studio = PhotoStudio(library.root, library.workspace / "photos", library.workspace / "p.db")
    real = studio.render(
        PhotoRecipe(format="photo", sources=[catalog.get(parent.id)], runtime=runtime_identity())
    )
    ai = studio.render(
        PhotoRecipe(format="photo", sources=[catalog.get(view.id)], runtime=runtime_identity())
    )
    assert not real.generated and ai.generated and not ai.reference_only


def test_dashboard_upload_review_mix_plan_and_safe_media(library, tmp_path):
    # TestClient's event loop needs a local socketpair; network sockets stay blocked.
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    runs = tmp_path / "outputs"
    runs.mkdir()
    client = TestClient(
        create_app(workspace=library.workspace, brand=demo_brand(), runs=runs, root=tmp_path)
    )
    page = client.get("/")
    assert page.status_code == 200 and "Weekly mix" in page.text
    data = "data:image/jpeg;base64," + base64.b64encode(jpeg((1, 2, 3))).decode()
    upload = {"name": "a.jpg", "data_base64": data, "rights_confirmed": True, "added_by": "Owner"}
    created = client.post("/api/assets", json=upload).json()
    assert created["needs_review"] and created["origin"] == "owner"
    assert client.post("/api/assets", json={**upload, "data_base64": "@@"}).status_code == 422
    assert client.post("/api/assets", json={**upload, "rights_confirmed": False}).status_code == 422
    assert (
        client.patch(f"/api/assets/{created['id']}", json={"owner_pillar": "x"}).status_code == 422
    )
    done = client.patch(
        f"/api/assets/{created['id']}",
        json={"owner_pillar": "spa", "note_en": "Pool", "note_ar": "مسبح"},
    ).json()
    assert done["usable"] and not done["needs_review"]
    summary = client.get("/api/summary").json()
    assert summary["assets"]["usable"] == 1 and summary["engine"] is None
    assert client.post("/api/classify").status_code == 409
    bad = {"posts_per_week": 3, "reels_per_week": 3, "carousels_per_week": 1}
    assert client.put("/api/cadence", json=bad).status_code == 422
    good = {"posts_per_week": 7, "reels_per_week": 3, "carousels_per_week": 2}
    assert client.put("/api/cadence", json=good).json()["photos_per_week"] == 2
    plan = client.get("/api/plan?week_start=2026-10-14").json()
    assert plan["week_start"] == "2026-10-12" and len(plan["slots"]) == 7
    assert sum(s["format"] == "reel" for s in plan["slots"]) == 3
    assert (
        client.get(f"/media/assets/{created['id']}?w=120").headers["content-type"] == "image/jpeg"
    )
    assert client.get("/media/run?path=../ws/assets.sqlite").status_code == 404
    (tmp_path / ".env").write_text("SECRET=1")
    assert client.get("/media/run?path=.env").status_code == 404
    assert client.get("/media/run?path=ws/assets.sqlite").status_code == 404
    assert client.get("/api/runs").json() == []
    assert (
        client.post(f"/api/assets/{created['id']}/variants", json={"preset": "aerial"}).status_code
        == 409
    )


def test_view_score_is_the_weaker_d3_answer(library):
    parent = owner_photo(library, 9, "local")
    view = make_view(library, parent, "aerial", 1, backend=StubViewBackend(), revision="r")
    assert view.view_score is None
    library.record_fidelity(view.id, {"same_place": 0.95, "photoreal": 0.49})
    assert library.get(view.id).view_score == 0.49


def test_new_shot_uses_several_owner_photos_and_counts_as_their_spot(library):
    from instabay.assets.plan import family
    from instabay.assets.variants import make_shot

    a = library.add(jpeg((10, 90, 160), (1200, 1500)), added_by="o", rights_confirmed=True)
    b = library.add(jpeg((90, 10, 160), (1200, 1500)), added_by="o", rights_confirmed=True)
    a, b = library.review(a.id, owner_pillar="spa"), library.review(b.id, owner_pillar="spa")
    shot = make_shot(library, [a, b], "spa", 0, 7, backend=StubViewBackend(), revision="r")
    assert shot.origin == "generated" and shot.pillar == "spa" and not shot.usable
    assert shot.recipe and shot.recipe["parents"] == [a.id, b.id]
    assert (
        shot.recipe["kind"] == "new-shot-v1" and "Use only the buildings" in shot.recipe["prompt"]
    )
    assert family(shot) == {a.id, b.id}
    with pytest.raises(ValueError, match="real photos"):
        make_shot(library, [shot], "spa", 0, 7, backend=StubViewBackend(), revision="r")


def test_owner_approved_ai_shot_can_be_a_reel_keyframe_but_not_other_synthetic():
    from instabay.video.shotlist import Keyframe

    base = dict(
        uri="outputs/k.jpg",
        sha256="a" * 64,
        source="synthetic",
        scene="mood",
        approved_by="owner",
        approval_id="x",
        faces_checked=True,
        attribution="AI view",
        reference_only=False,
    )
    assert Keyframe(**base, approval_scope="owner_approved_view").source == "synthetic"
    with pytest.raises(ValueError, match="reference-only"):
        Keyframe(**base)


def test_gpu_actions_reconnect_first_and_explain_when_gpu_box_is_off(library, tmp_path):
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    calls = []

    def down():
        calls.append(1)
        raise RuntimeError("ssh: connect timed out")

    parent = owner_photo(library, 61, "spa")
    runs = tmp_path / "outputs"
    runs.mkdir()
    client = TestClient(
        create_app(
            workspace=library.workspace,
            brand=demo_brand(),
            runs=runs,
            root=tmp_path,
            variants=lambda lib, a, preset, seed: a,
            gpu_ready=down,
        )
    )
    response = client.post(f"/api/assets/{parent.id}/variants", json={"preset": "aerial"})
    assert response.status_code == 503 and "PC is on" in response.json()["detail"]
    assert calls == [1]
