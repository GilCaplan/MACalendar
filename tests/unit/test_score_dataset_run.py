"""The dataset scorer's garbage-title reading — the instrument, tested alone.

Cycle 28 (2026-09-20): the test was seven joiner words, and every run of the
month read 0% garbage while 'note', 'remind me' and 'take out the trash. also'
were being written. The three readings below are the shapes the dev-100
checkpoint actually produced; the negatives are titles a speaker means."""
import pytest

from scripts.score_dataset_run import is_garbage_title


@pytest.mark.parametrize("title", [
    "and then", "note", "date ?", "event", "new list", "Calendar event", "note of it",
    "remind me", "remind of my dentist appointment", "Send me a reminder to pick up my dog from the groomer",
    "create a list", "Open calendar", "this on my calender",
    "take out the trash. also", "remind when it is lunchtime and then i", "grocery shopping 's to-do list",
    "pda do i have any appointments set ?", "make 's to-do list", "For the next three remind me I have yoga class , and then yashas bithday",
])
def test_a_title_that_is_not_a_title(title):
    assert is_garbage_title(title), title


@pytest.mark.parametrize("title", [
    "dentist", "gym", "flu shot", "team meeting", "dinner reservations", "call mom", "buy milk", "add water",
    "milk", "physical therapy", "yoga class", "Hayat's daughter baby shower", "brother's birthday dinner at rusk",
    "note taking workshop", "date night", "meeting with laura", "walk the dog", "pick up my dog from the groomer",
])
def test_a_title_a_speaker_means(title):
    assert not is_garbage_title(title), title
