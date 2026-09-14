"""Unit tests for the Coordinator's in-memory state machine."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest

from coordinator.models.video import PartyShareStatus, VideoStatus
from coordinator.services.video_service import (
    DEFAULT_PARTY_URLS,
    UnsupportedVideoFormatError,
    VideoNotFoundError,
    VideoService,
    load_party_urls,
)


@pytest.fixture
def service() -> VideoService:
    return VideoService(DEFAULT_PARTY_URLS)


def test_register_video_returns_uuid4_initial_state_and_ordered_party_urls(
    service: VideoService,
) -> None:
    registration = service.register_video("camera-01.mp4", "mp4")

    assert isinstance(registration.id, UUID)
    assert registration.id.version == 4
    assert registration.status is VideoStatus.WAITING_FOR_SHARES
    assert [(party.id, party.url) for party in registration.parties] == [
        (0, "http://localhost:8100"),
        (1, "http://localhost:8101"),
        (2, "http://localhost:8102"),
    ]

    state = service.get_video(registration.id)
    assert state.status is VideoStatus.WAITING_FOR_SHARES
    assert state.parties == {
        "0": PartyShareStatus.PENDING,
        "1": PartyShareStatus.PENDING,
        "2": PartyShareStatus.PENDING,
    }


def test_register_video_normalizes_filename_and_mp4_spelling(
    service: VideoService,
) -> None:
    registration = service.register_video("  camera.mp4  ", " .MP4 ")

    assert service.get_video(registration.id).status is VideoStatus.WAITING_FOR_SHARES


@pytest.mark.parametrize("video_format", ["", " ", "avi", "mov", "mkv", "txt", "mp3"])
def test_register_video_rejects_unsupported_formats(
    service: VideoService,
    video_format: str,
) -> None:
    with pytest.raises(UnsupportedVideoFormatError, match="Only MP4"):
        service.register_video("video.mp4", video_format)


@pytest.mark.parametrize("filename", ["", " ", "\t\r\n"])
def test_register_video_rejects_blank_filename(
    service: VideoService,
    filename: str,
) -> None:
    with pytest.raises(ValueError, match="filename must not be blank"):
        service.register_video(filename, "mp4")


def test_multiple_registrations_have_unique_ids_and_independent_state(
    service: VideoService,
) -> None:
    registrations = [
        service.register_video(f"video-{index}.mp4", "mp4") for index in range(3)
    ]

    assert len({registration.id for registration in registrations}) == 3

    service.confirm_share(registrations[0].id, 0)
    assert service.get_video(registrations[0].id).parties["0"] is PartyShareStatus.RECEIVED
    assert service.get_video(registrations[1].id).parties["0"] is PartyShareStatus.PENDING
    assert service.get_video(registrations[2].id).parties["0"] is PartyShareStatus.PENDING


def test_ten_concurrent_registrations_are_unique_and_retrievable(
    service: VideoService,
) -> None:
    def register(index: int):
        return service.register_video(f"concurrent-{index}.mp4", "mp4")

    with ThreadPoolExecutor(max_workers=5) as executor:
        registrations = list(executor.map(register, range(10)))

    ids = [registration.id for registration in registrations]
    assert len(ids) == len(set(ids)) == 10
    assert all(
        service.get_video(video_id).status is VideoStatus.WAITING_FOR_SHARES
        for video_id in ids
    )


def test_confirmation_progression_reaches_ready_only_after_all_three_parties(
    service: VideoService,
) -> None:
    video_id = service.register_video("video.mp4", "mp4").id

    after_party_0 = service.confirm_share(video_id, 0)
    assert after_party_0.status is VideoStatus.WAITING_FOR_SHARES
    assert after_party_0.parties == {
        "0": PartyShareStatus.RECEIVED,
        "1": PartyShareStatus.PENDING,
        "2": PartyShareStatus.PENDING,
    }

    after_party_1 = service.confirm_share(video_id, 1)
    assert after_party_1.status is VideoStatus.WAITING_FOR_SHARES
    assert after_party_1.parties["2"] is PartyShareStatus.PENDING

    after_party_2 = service.confirm_share(video_id, 2)
    assert after_party_2.status is VideoStatus.READY_FOR_MPC
    assert set(after_party_2.parties.values()) == {PartyShareStatus.RECEIVED}


def test_repeated_confirmation_is_idempotent(service: VideoService) -> None:
    video_id = service.register_video("video.mp4", "mp4").id

    first = service.confirm_share(video_id, 0)
    second = service.confirm_share(video_id, 0)
    third = service.confirm_share(video_id, 0)

    assert first == second == third
    assert third.status is VideoStatus.WAITING_FOR_SHARES
    assert third.parties["0"] is PartyShareStatus.RECEIVED
    assert third.parties["1"] is PartyShareStatus.PENDING
    assert third.parties["2"] is PartyShareStatus.PENDING


@pytest.mark.parametrize("party_id", [-1, 3, 99])
def test_service_rejects_unknown_party_without_corrupting_state(
    service: VideoService,
    party_id: int,
) -> None:
    video_id = service.register_video("video.mp4", "mp4").id

    with pytest.raises(ValueError, match="Unknown party_id"):
        service.confirm_share(video_id, party_id)

    state = service.get_video(video_id)
    assert state.status is VideoStatus.WAITING_FOR_SHARES
    assert set(state.parties.values()) == {PartyShareStatus.PENDING}


@pytest.mark.parametrize("party_id", [True, False, "0", "1", 0.0, 1.0])
def test_service_rejects_non_integer_party_ids(
    service: VideoService,
    party_id: object,
) -> None:
    video_id = service.register_video("video.mp4", "mp4").id

    with pytest.raises(ValueError, match="Unknown party_id"):
        service.confirm_share(video_id, party_id)  # type: ignore[arg-type]

    assert set(service.get_video(video_id).parties.values()) == {
        PartyShareStatus.PENDING
    }


def test_unknown_video_is_rejected_for_read_and_confirmation(
    service: VideoService,
) -> None:
    unknown_id = uuid4()

    with pytest.raises(VideoNotFoundError):
        service.get_video(unknown_id)
    with pytest.raises(VideoNotFoundError):
        service.confirm_share(unknown_id, 0)
    with pytest.raises(VideoNotFoundError):
        service.get_video(unknown_id)


def test_concurrent_confirmations_do_not_mix_jobs(service: VideoService) -> None:
    first_id = service.register_video("first.mp4", "mp4").id
    second_id = service.register_video("second.mp4", "mp4").id
    confirmations = [
        (first_id, 0),
        (second_id, 2),
        (first_id, 1),
        (second_id, 1),
        (first_id, 2),
    ]

    with ThreadPoolExecutor(max_workers=5) as executor:
        list(executor.map(lambda item: service.confirm_share(*item), confirmations))

    first = service.get_video(first_id)
    second = service.get_video(second_id)
    assert first.status is VideoStatus.READY_FOR_MPC
    assert second.status is VideoStatus.WAITING_FOR_SHARES
    assert second.parties == {
        "0": PartyShareStatus.PENDING,
        "1": PartyShareStatus.RECEIVED,
        "2": PartyShareStatus.RECEIVED,
    }


def test_concurrent_repeated_confirmations_reach_a_consistent_ready_state(
    service: VideoService,
) -> None:
    video_id = service.register_video("video.mp4", "mp4").id
    party_ids = [0, 1, 2] * 10

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(lambda party_id: service.confirm_share(video_id, party_id), party_ids))

    state = service.get_video(video_id)
    assert state.status is VideoStatus.READY_FOR_MPC
    assert set(state.parties.values()) == {PartyShareStatus.RECEIVED}


def test_new_service_instance_has_no_persisted_jobs(service: VideoService) -> None:
    video_id = service.register_video("video.mp4", "mp4").id
    restarted_service = VideoService(DEFAULT_PARTY_URLS)

    with pytest.raises(VideoNotFoundError):
        restarted_service.get_video(video_id)


def test_video_service_requires_exactly_three_parties() -> None:
    with pytest.raises(ValueError, match="exactly three parties"):
        VideoService(("http://party-0", "http://party-1"))
    with pytest.raises(ValueError, match="exactly three parties"):
        VideoService((*DEFAULT_PARTY_URLS, "http://party-3"))


def test_load_party_urls_defaults_and_normalizes_configuration(monkeypatch) -> None:
    monkeypatch.delenv("PARTY_URLS", raising=False)
    assert load_party_urls() == DEFAULT_PARTY_URLS
    assert load_party_urls(
        " http://party-0:8100/,https://party-1:8101/,http://party-2:8102/ "
    ) == (
        "http://party-0:8100",
        "https://party-1:8101",
        "http://party-2:8102",
    )

    monkeypatch.setenv(
        "PARTY_URLS",
        "http://configured-0,http://configured-1,http://configured-2",
    )
    assert load_party_urls() == (
        "http://configured-0",
        "http://configured-1",
        "http://configured-2",
    )


@pytest.mark.parametrize(
    "raw_value",
    [
        "",
        "http://party-0,http://party-1",
        "http://party-0,http://party-1,http://party-2,http://party-3",
        "party-0,http://party-1,http://party-2",
        "ftp://party-0,http://party-1,http://party-2",
    ],
)
def test_load_party_urls_rejects_invalid_configuration(raw_value: str) -> None:
    with pytest.raises(RuntimeError):
        load_party_urls(raw_value)
