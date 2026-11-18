"""HTTP surface tests. Runs are real: submit, poll, read the result."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from engine import api


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYTOLENS_RUNS_DB", str(tmp_path / "runs.db"))
    with TestClient(api.app) as test_client:
        yield test_client


def wait_for_run(client, run_id, timeout=90.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/v1/runs/{run_id}").json()
        if payload["status"] in {"complete", "failed"}:
            return payload
        time.sleep(0.25)
    pytest.fail(f"run {run_id} did not finish in {timeout}s")


def create_run(client, **overrides):
    body = {"plant": "Curcuma longa", "part": "rhizome", "solvent": "ethanol",
            "condition": "colitis", "top": 8}
    body.update(overrides)
    response = client.post("/v1/runs", json=body)
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


# --------------------------------------------------------------------------
# ops
# --------------------------------------------------------------------------
def test_health_reports_corpus_and_engine(client):
    payload = client.get("/v1/health").json()
    assert payload["status"] == "ok"
    assert payload["corpus"]["compounds"] > 10_000
    assert payload["corpus"]["plants"] > 1_000
    assert "colitis" in payload["conditions"]
    # CI has no Vina binary, so health must report availability rather than
    # claim a version. Locally (and on the demo machine) it reports the version.
    assert isinstance(payload["vina"], str) and payload["vina"]
    assert payload["queue"]["backend"] in {"redis", "inline"}


def test_version(client):
    payload = client.get("/v1/version").json()
    assert payload["version"] == api.VERSION


# --------------------------------------------------------------------------
# resolution
# --------------------------------------------------------------------------
def test_plant_search_resolves_common_name(client):
    payload = client.get("/v1/plants", params={"q": "turmeric"}).json()
    assert payload["results"]
    assert any("Curcuma" in r["plant"] for r in payload["results"])


def test_plant_search_returns_one_row_per_plant(client):
    results = client.get("/v1/plants", params={"q": "curcuma", "limit": 8}).json()["results"]
    ids = [row["id"] for row in results]
    assert ids
    assert len(ids) == len(set(ids)), "the same plant must not appear twice"


def test_cors_preflight_allows_loopback_and_tunnels(client):
    allowed = ["http://127.0.0.1:3000", "http://localhost:3001",
               "https://reply-justness-paramedic.ngrok-free.dev",
               "https://demo.trycloudflare.com"]
    for origin in allowed:
        response = client.options("/v1/runs", headers={
            "Origin": origin, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        assert response.status_code == 200, origin
        assert response.headers["access-control-allow-origin"] == origin

    denied = client.options("/v1/runs", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_conditions_are_listed_and_filterable(client):
    assert len(client.get("/v1/conditions").json()["conditions"]) >= 2
    assert client.get("/v1/conditions", params={"q": "colit"}).json()["conditions"]


def test_formulation_resolves_parts(client):
    response = client.post("/v1/formulations", json={
        "plant": "Curcuma longa", "part": "rhizome", "solvent": "ethanol"})
    assert response.status_code == 201
    body = response.json()
    assert body["plant"] == "Curcuma longa"
    assert body["solvent_label"].startswith("ethanol")
    assert body["compounds_in_part"] == 168


def test_formulation_is_stored_and_addressable(client):
    created = client.post("/v1/formulations", json={
        "plant": "Boswellia serrata", "part": "exudate", "solvent": "ethanol"})
    assert created.status_code == 201
    body = created.json()
    assert body["formulation_id"].startswith("frm_")
    fetched = client.get(f"/v1/formulations/{body['formulation_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["plant"] == "Boswellia serrata"
    assert client.get("/v1/formulations/frm_missing").status_code == 404


def test_unknown_plant_is_404(client):
    response = client.post("/v1/formulations", json={
        "plant": "Unobtainium officinalis", "part": "root", "solvent": "ethanol"})
    assert response.status_code == 404


def test_unknown_part_lists_available_parts(client):
    response = client.post("/v1/formulations", json={
        "plant": "Curcuma longa", "part": "wing", "solvent": "ethanol"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["available_parts"]


def test_structures_include_provenance(client):
    body = client.get("/v1/structures/PTGS2").json()
    assert body["pdb_id"] == "3NT1"
    assert body["tier"] == "A"
    assert body["source"] == "RCSB PDB"
    assert body["ligand_code"] == "NPS"
    assert body["box"]["size"] == [20.0, 20.0, 20.0]
    assert client.get("/v1/structures/NOPE").status_code == 404

    pdb = client.get("/v1/structures/ALOX5/pdb")
    assert pdb.status_code == 200
    assert "ATOM" in pdb.text


def test_docking_pose_returns_modes_contacts_and_2d_svg(client):
    demo = client.get("/v1/demo").json()
    top = demo["ranked"][0]
    resp = client.get(f"/v1/docking/pose/{top['id']}/ALOX5")
    assert resp.status_code == 200
    pose = resp.json()
    assert pose["pdb_id"] == "3V99"
    assert len(pose["modes"]) >= 1
    assert "HETATM" in pose["modes"][0]["pdb_block"]
    assert pose["contacts"]
    assert pose["svg_2d"] and "<svg" in pose["svg_2d"]
    assert client.get("/v1/docking/pose/cmp_missing/ALOX5").status_code == 404


# --------------------------------------------------------------------------
# runs
# --------------------------------------------------------------------------
def test_run_lifecycle_shortlist_network_and_pdf(client):
    run_id = create_run(client)
    final = wait_for_run(client, run_id)
    assert final["status"] == "complete", final
    assert final["progress"] == 1.0

    shortlist = client.get(f"/v1/runs/{run_id}/shortlist").json()
    assert shortlist["formulation"]["plant"] == "Curcuma longa"
    assert shortlist["condition"]["name"]
    assert shortlist["ranked"][0]["rank"] == 1
    assert len(shortlist["ranked"]) == 8

    network = client.get(f"/v1/runs/{run_id}/network").json()
    assert network["nodes"] and network["edges"] and network["hubs"]
    assert any(n["type"] == "condition" for n in network["nodes"])

    pdf = client.get(f"/v1/runs/{run_id}/report.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 4_000


def test_unknown_run_is_404(client):
    assert client.get("/v1/runs/run_missing").status_code == 404
    assert client.get("/v1/runs/run_missing/shortlist").status_code == 404
    assert client.get("/v1/runs/run_missing/report.pdf").status_code == 404


def test_unknown_condition_is_rejected(client):
    response = client.post("/v1/runs", json={
        "plant": "Curcuma longa", "part": "rhizome", "condition": "everything"})
    assert response.status_code == 400


def test_shortlist_before_completion_is_409(client):
    run_id = create_run(client, top=5)
    response = client.get(f"/v1/runs/{run_id}/shortlist")
    # Either still running (409) or already finished on a fast machine.
    assert response.status_code in {200, 409}


def test_demo_returns_precomputed_shortlist(client):
    payload = client.get("/v1/demo").json()
    assert payload["demo"] is True
    assert payload["formulation"]["plant"] == "Curcuma longa"
    assert payload["ranked"]
    assert payload["ranked"][0]["docking"] is not None
    assert payload["docking_pending"] is False
    coverage = payload["docking"]
    assert coverage["candidates"] == coverage["docked"]
    assert coverage["partial"] is False


def test_run_reports_which_queue_it_used(client):
    run_id = create_run(client, top=5)
    final = wait_for_run(client, run_id)
    assert final["status"] == "complete"
    response = client.post("/v1/runs", json={"plant": "Curcuma longa", "part": "rhizome",
                                          "condition": "colitis", "top": 5})
    assert response.json()["queue"] in {"redis", "inline"}


# --------------------------------------------------------------------------
# browsing helpers
# --------------------------------------------------------------------------
def test_parts_endpoint_does_not_create_a_formulation(client):
    hits = client.get("/v1/plants", params={"q": "turmeric"}).json()["results"]
    body = client.get(f"/v1/plants/{hits[0]['id']}/parts").json()
    assert body["parts"]
    assert any(part["part"] == "rhizome" for part in body["parts"])
    assert client.get("/v1/plants/plant_missing/parts").status_code == 404


# --------------------------------------------------------------------------
# live docking (Vina is stubbed; the real path is exercised by the CLI)
# --------------------------------------------------------------------------
def _fake_dock_live(compounds, targets, exhaustiveness=4):
    cid, name, _smiles = compounds[0]
    scores = {cid: {"name": name, "targets": {
        t: {"affinity": -9.5, "ligand_efficiency": -0.4, "seconds": 1.2,
            "cached": False, "key": "deadbeef"} for t in targets}}}
    return {
        "scores": scores,
        "affinities": {cid: {t: -9.5 for t in targets}},
        "fresh": 1, "reused": 0,
        "engine": "AutoDock Vina", "vina": "AutoDock Vina v1.2.7",
        "seed": 42, "exhaustiveness": exhaustiveness,
        "targets": {t: {"pdb_id": "3NT1", "ligand_code": "NPS",
                          "box": {"center": [0, 0, 0], "size": [20, 20, 20]},
                          "source": "RCSB PDB"} for t in targets},
    }


def test_live_dock_merges_fresh_scores_into_the_shortlist(client, monkeypatch):
    run_id = create_run(client)
    assert wait_for_run(client, run_id)["status"] == "complete"
    monkeypatch.setattr(api.dk, "dock_live", _fake_dock_live)

    response = client.post(f"/v1/runs/{run_id}/dock",
                           json={"targets": ["PTGS2"], "candidates": 2})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["fresh"] == 1
    assert body["vina"].startswith("AutoDock Vina")
    docked = body["affinities"]
    assert docked
    cid = next(iter(docked))
    assert docked[cid]["PTGS2"] == -9.5
    assert all(row["docking"].get("PTGS2") != -9.5
               for row in body["shortlist"] if row["id"] != cid)

    # The stored run is updated, so a page reload shows the live result.
    stored = client.get(f"/v1/runs/{run_id}/shortlist").json()
    assert stored["ranked"] == body["shortlist"]


def test_live_dock_rejects_unknown_target_and_compound(client):
    run_id = create_run(client)
    assert wait_for_run(client, run_id)["status"] == "complete"
    bad_target = client.post(f"/v1/runs/{run_id}/dock",
                             json={"targets": ["NOT_A_TARGET"]})
    assert bad_target.status_code == 400
    bad_compound = client.post(f"/v1/runs/{run_id}/dock",
                               json={"compound_ids": ["cmp_missing"]})
    assert bad_compound.status_code == 400
    assert client.post("/v1/runs/run_missing/dock", json={}).status_code == 404


# --------------------------------------------------------------------------
# rate limits + auth
# --------------------------------------------------------------------------
def test_rate_limit_returns_429_with_headers(client, monkeypatch):
    monkeypatch.delenv("PHYTOLENS_RATE_LIMIT_DISABLED", raising=False)
    monkeypatch.setenv("PHYTOLENS_RATE_LIMIT_SCALE", "0.01")  # demo 60 -> 1
    api.ratelimit.reset()

    first = client.get("/v1/demo")
    assert first.status_code == 200
    assert first.headers["x-ratelimit-limit"] == "1"
    assert first.headers["x-ratelimit-backend"] in {"redis", "memory"}

    second = client.get("/v1/demo")
    assert second.status_code == 429
    assert second.headers["retry-after"].isdigit()
    assert second.json()["bucket"] == "v1:demo"


def test_writes_require_an_api_key_when_configured(client, monkeypatch):
    monkeypatch.setenv("PHYTOLENS_API_KEY", "test-key-123")
    body = {"plant": "Curcuma longa", "part": "rhizome", "solvent": "ethanol"}

    missing = client.post("/v1/formulations", json=body)
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    wrong = client.post("/v1/formulations", json=body,
                        headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 403

    good = client.post("/v1/formulations", json=body,
                       headers={"Authorization": "Bearer test-key-123"})
    assert good.status_code == 201
    assert "test-key-123" not in good.text

    # Reads stay public: a report can be opened without the key.
    assert client.get("/v1/demo").status_code == 200


def test_run_records_who_requested_it(client, monkeypatch):
    monkeypatch.setenv("PHYTOLENS_API_KEY", "owner-key")
    response = client.post("/v1/runs",
                           json={"plant": "Curcuma longa", "part": "rhizome",
                                 "condition": "colitis", "top": 5},
                           headers={"Authorization": "Bearer owner-key"})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    final = wait_for_run(client, run_id)
    assert final["owner"].startswith("key_")
    assert "owner-key" not in str(final)


# --------------------------------------------------------------------------
# validation wiring
# --------------------------------------------------------------------------
def test_validation_endpoint_serves_the_harness(client, monkeypatch):
    from engine import validation as val

    api._VALIDATION_CACHE.clear()
    monkeypatch.setattr(val, "run_all",
                        lambda write=False: {"aggregate": {"n_cases": 0},
                                             "cases": [], "corpus_bias": {}})
    assert client.get("/v1/validation").json()["aggregate"]["n_cases"] == 0
    api._VALIDATION_CACHE.clear()


def test_run_records_are_isolated_by_database(client, tmp_path):
    run_id = create_run(client, plant="Boswellia serrata", part="exudate")
    final = wait_for_run(client, run_id)
    assert final["status"] == "complete", final
    shortlist = client.get(f"/v1/runs/{run_id}/shortlist").json()
    assert shortlist["formulation"]["plant"] == "Boswellia serrata"
