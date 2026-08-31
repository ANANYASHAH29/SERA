"""Tests for the one-click CI-automation setup: commits the workflow +
reporter script and sets the three secrets/variables a repo needs, via
the installation token -- replacing the old copy-paste-by-hand Settings
page instructions. GitHub network calls are faked; these test the
create-vs-update branching and the 403-on-missing-permissions path.
"""
from github import GithubException

from sera.method.ci_autosetup import setup_ci_reporting


class FakeContentFile:
    sha = "abc123"


class FakeVariable:
    def __init__(self, value):
        self.value = value
        self.edited_to = None

    def edit(self, value):
        self.edited_to = value


class FakeRepo:
    def __init__(self, existing_files=(), existing_variables=None, secrets_raise=None):
        self.existing_files = set(existing_files)
        self.created_files = {}
        self.updated_files = {}
        self.variables = existing_variables or {}
        self.created_variables = {}
        self.secrets = {}
        self._secrets_raise = secrets_raise

    def get_contents(self, path):
        if path in self.existing_files:
            return FakeContentFile()
        from github import UnknownObjectException

        raise UnknownObjectException(404, {"message": "Not Found"}, {})

    def create_file(self, path, message, content):
        self.created_files[path] = content

    def update_file(self, path, message, content, sha):
        self.updated_files[path] = content

    def create_variable(self, name, value):
        if name in self.variables:
            from github import GithubException

            raise GithubException(422, {"message": "already exists"}, {})
        self.created_variables[name] = value

    def get_variable(self, name):
        return self.variables[name]

    def create_secret(self, name, value):
        if self._secrets_raise:
            raise self._secrets_raise
        self.secrets[name] = value


class FakeClient:
    def __init__(self, repo):
        self._repo = repo

    def get_repo(self, full_name):
        return self._repo


def test_creates_new_files_and_secrets_for_a_repo_with_none_yet(monkeypatch):
    fake_repo = FakeRepo()
    monkeypatch.setattr("sera.method.ci_autosetup.Github", lambda token: FakeClient(fake_repo))

    result = setup_ci_reporting("alice/repo", "fake-token", "https://sera.example.com", 7, "sekret")

    assert result["status"] == "configured"
    assert result["workflow_file"] == "created"
    assert result["reporter_script"] == "created"
    assert ".github/workflows/sera_report_scan.yml" in fake_repo.created_files
    assert ".github/scripts/report_scan.py" in fake_repo.created_files
    assert fake_repo.created_variables["SERA_DASHBOARD_URL"] == "https://sera.example.com"
    assert fake_repo.secrets["SERA_REPO_ID"] == "7"
    assert fake_repo.secrets["SERA_REPORT_TOKEN"] == "sekret"


def test_updates_existing_files_instead_of_recreating(monkeypatch):
    fake_repo = FakeRepo(existing_files={".github/workflows/sera_report_scan.yml", ".github/scripts/report_scan.py"})
    monkeypatch.setattr("sera.method.ci_autosetup.Github", lambda token: FakeClient(fake_repo))

    result = setup_ci_reporting("alice/repo", "fake-token", "https://sera.example.com", 7, "sekret")

    assert result["workflow_file"] == "updated"
    assert result["reporter_script"] == "updated"
    assert ".github/workflows/sera_report_scan.yml" in fake_repo.updated_files
    assert not fake_repo.created_files


def test_edits_variable_when_it_already_exists(monkeypatch):
    existing_var = FakeVariable("https://old.example.com")
    fake_repo = FakeRepo(existing_variables={"SERA_DASHBOARD_URL": existing_var})
    monkeypatch.setattr("sera.method.ci_autosetup.Github", lambda token: FakeClient(fake_repo))

    setup_ci_reporting("alice/repo", "fake-token", "https://sera.example.com", 7, "sekret")

    assert existing_var.edited_to == "https://sera.example.com"


def test_propagates_github_exception_when_permissions_missing(monkeypatch):
    fake_repo = FakeRepo(secrets_raise=GithubException(403, {"message": "Resource not accessible"}, {}))
    monkeypatch.setattr("sera.method.ci_autosetup.Github", lambda token: FakeClient(fake_repo))

    try:
        setup_ci_reporting("alice/repo", "fake-token", "https://sera.example.com", 7, "sekret")
        assert False, "expected GithubException"
    except GithubException as e:
        assert e.status == 403
