import pytest
from django.http import Http404

from plane.authentication.provider.oauth.mog import MogOAuthProvider
from plane.db.models import WorkspaceMember
from plane.tests.factories import UserFactory, WorkspaceFactory, WorkspaceMemberFactory


def make_provider():
    provider = object.__new__(MogOAuthProvider)
    provider.tracker_access_url = ""
    provider.tracker_access_api_key = ""
    provider.tracker_workspace_slug = "mog-deadlock"
    return provider


def test_set_user_data_allows_staff_or_contributor_roles():
    provider = make_provider()
    provider.get_user_response = lambda: {
        "sub": "019d9d94-98a1-70ff-9f1a-3981b5db6698",
        "name": "civo",
        "picture": "https://avatars.steamstatic.com/civo_full.jpg",
        "mog_roles": ["developer"],
    }

    provider.set_user_data()

    assert provider.user_data["email"] == (
        "019d9d94-98a1-70ff-9f1a-3981b5db6698@mog-deadlock.local"
    )
    assert provider.user_data["user"]["display_name"] == "civo"
    assert provider.user_data["user"]["mog_roles"] == ["developer"]


def test_set_user_data_denies_plain_players():
    provider = make_provider()
    provider.get_user_response = lambda: {
        "sub": "019d9d94-98a1-70ff-9f1a-3981b5db6698",
        "name": "plain-player",
        "mog_roles": [],
    }

    with pytest.raises(Http404):
        provider.set_user_data()


def test_set_user_data_denies_vip_only():
    provider = make_provider()
    provider.get_user_response = lambda: {
        "sub": "019d9d94-98a1-70ff-9f1a-3981b5db6698",
        "name": "vip-player",
        "mog_roles": ["vip"],
    }

    with pytest.raises(Http404):
        provider.set_user_data()


@pytest.mark.django_db
def test_ensure_tracker_workspace_membership_adds_member_role():
    provider = make_provider()
    user = UserFactory()
    workspace = WorkspaceFactory(slug="mog-deadlock")

    provider.ensure_tracker_workspace_membership(user)

    workspace_member = WorkspaceMember.objects.get(workspace=workspace, member=user)
    assert workspace_member.role == 15
    assert workspace_member.is_active is True


@pytest.mark.django_db
def test_ensure_tracker_workspace_membership_does_not_downgrade_admin():
    provider = make_provider()
    user = UserFactory()
    workspace = WorkspaceFactory(slug="mog-deadlock")
    WorkspaceMemberFactory(workspace=workspace, member=user, role=20)

    provider.ensure_tracker_workspace_membership(user)

    workspace_member = WorkspaceMember.objects.get(workspace=workspace, member=user)
    assert workspace_member.role == 20
    assert workspace_member.is_active is True
