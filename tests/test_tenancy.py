"""Explicit tenant-isolation test: one user must never be able to query
or see another user's repo/incident data, even by guessing/enumerating
ids. This is the one test in the multi-tenant phase that matters most --
everything else in tenancy.py exists to make this true.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sera.db.models import Base, ConnectedRepo, Incident, ScanResult
from sera.method.tenancy import (
    NotFoundOrNotOwned,
    get_or_create_user,
    get_owned_incident,
    get_owned_repo,
    list_owned_repos,
    list_owned_scan_results,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    s = factory()
    yield s
    s.close()


@pytest.fixture
def two_tenants(session):
    alice = get_or_create_user(session, "alice", installation_id=111)
    bob = get_or_create_user(session, "bob", installation_id=222)
    session.flush()

    alice_repo = ConnectedRepo(user_id=alice.id, repo_full_name="alice/cv-pipeline")
    bob_repo = ConnectedRepo(user_id=bob.id, repo_full_name="bob/cv-pipeline")
    session.add_all([alice_repo, bob_repo])
    session.flush()

    alice_scan = ScanResult(repo_id=alice_repo.id, status="incident", summary_json="{}")
    bob_scan = ScanResult(repo_id=bob_repo.id, status="healthy", summary_json="{}")
    session.add_all([alice_scan, bob_scan])

    alice_incident = Incident(connected_repo_id=alice_repo.id, accuracy_drop=0.2)
    bob_incident = Incident(connected_repo_id=bob_repo.id, accuracy_drop=0.1)
    session.add_all([alice_incident, bob_incident])
    session.commit()

    return {
        "alice": alice,
        "bob": bob,
        "alice_repo": alice_repo,
        "bob_repo": bob_repo,
        "alice_incident": alice_incident,
        "bob_incident": bob_incident,
    }


def test_list_owned_repos_never_returns_another_users_repos(session, two_tenants):
    alice_repos = list_owned_repos(session, two_tenants["alice"].id)
    assert [r.repo_full_name for r in alice_repos] == ["alice/cv-pipeline"]

    bob_repos = list_owned_repos(session, two_tenants["bob"].id)
    assert [r.repo_full_name for r in bob_repos] == ["bob/cv-pipeline"]


def test_get_owned_repo_rejects_cross_tenant_access(session, two_tenants):
    bob_id = two_tenants["bob"].id
    alice_repo_id = two_tenants["alice_repo"].id

    with pytest.raises(NotFoundOrNotOwned):
        get_owned_repo(session, bob_id, alice_repo_id)

    # bob CAN fetch his own repo by id, proving the rejection above is
    # about ownership, not a broken query.
    own = get_owned_repo(session, bob_id, two_tenants["bob_repo"].id)
    assert own.repo_full_name == "bob/cv-pipeline"


def test_get_owned_incident_rejects_cross_tenant_access(session, two_tenants):
    alice_id = two_tenants["alice"].id
    bob_incident_id = two_tenants["bob_incident"].id

    with pytest.raises(NotFoundOrNotOwned):
        get_owned_incident(session, alice_id, bob_incident_id)

    own = get_owned_incident(session, alice_id, two_tenants["alice_incident"].id)
    assert own.id == two_tenants["alice_incident"].id


def test_list_owned_scan_results_rejects_cross_tenant_repo_id(session, two_tenants):
    alice_id = two_tenants["alice"].id
    bob_repo_id = two_tenants["bob_repo"].id

    with pytest.raises(NotFoundOrNotOwned):
        list_owned_scan_results(session, alice_id, bob_repo_id)

    own_results = list_owned_scan_results(session, alice_id, two_tenants["alice_repo"].id)
    assert len(own_results) == 1
    assert own_results[0].status == "incident"


def test_nonexistent_repo_id_raises_same_error_as_wrong_owner(session, two_tenants):
    # A caller shouldn't be able to distinguish "doesn't exist" from
    # "exists but isn't yours" -- that distinction itself leaks which ids
    # are valid to a stranger probing the API.
    alice_id = two_tenants["alice"].id
    with pytest.raises(NotFoundOrNotOwned):
        get_owned_repo(session, alice_id, 999999)


def test_get_or_create_user_is_idempotent_per_github_username(session):
    a = get_or_create_user(session, "carol", installation_id=333)
    b = get_or_create_user(session, "carol", installation_id=333)
    assert a.id == b.id
