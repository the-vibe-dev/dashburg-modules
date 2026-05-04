from trend_harvester.services.channels import get_channel_profiles, get_channel_records


def test_channel_registry_contains_expected_dashburg_channels():
    names = {record.display_name for record in get_channel_records()}
    expected = {
        "Stateside Now",
        "Bharat Brief",
        "Truth Tellers Hub",
        "Forgotten Empire",
        "Daily Bible Passages",
        "Spoken in Light",
        "Brain Wave History",
        "Heartfelt Critter Chronicles",
        "Anime Bios",
        "Bite Sized Knowledge",
        "World News Shorts",
        "EuroScope",
        "Daily Signal",
        "Crime Stories Today",
        "Afrika Dispatch",
        "The Literary Theatre",
    }
    assert expected.issubset(names)


def test_channel_profiles_are_non_empty_for_registry_channels():
    profiles = get_channel_profiles()
    assert profiles["Truth Tellers Hub"]
    assert profiles["Stateside Now"]
    assert profiles["Bite Sized Knowledge"]
