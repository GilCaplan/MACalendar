# Dataset run score — `/var/folders/0f/nk3dnvrd54jbjz_qn40_ynwh0000gn/T/engine_compare_kjcp2mhx/engine_run.db`

- product-adjusted count-correct **81%** (6 overridden rows; raw below is the comparable number)
- **100 prompts** scored · count-correct **78%** · garbage-title rate **3%**
- total_ms p50 70 · p95 45984
- parse paths: {'deep': 65, 'fast': 35}

## By complexity

| Tier | n | count-correct | garbage titles | total_ms p50 |
|---|---:|---:|---:|---:|
| simple | 34 | 97% | 0% | 40 |
| medium | 33 | 88% | 0% | 53 |
| complex | 33 | 48% | 9% | 133 |

## By compound kind

| Kind | n | count-correct | garbage titles | dates collapsed |
|---|---:|---:|---:|---:|
| event+event | 11 | 45% | 0% | 18% |
| task+task | 11 | 55% | 18% | 0% |
| event+task | 11 | 45% | 9% | 0% |

## event+task: which half goes missing when it fails

- both present: 5 · event missing: 4 · task missing: 1 · both missing: 1

## Correctness by parse path

| Path | count-correct |
|---|---:|
| deep | 68% |
| fast | 97% |

## Count-mismatch failures (22)

- **On the fifth of November, I need to go to Washington, D.C, and then I'd like to set a date** — event+event: got 1 events, 0 tasks (wanted ≥2/≥0)
- **reopen groceries and add milk. Also, put xxx on the list** — task+task: got 1 events, 1 tasks (wanted ≥0/≥2)
- **REMIND ABOUT OF ALL EVENT IN CALENDERS** — medium: got 0 events, 0 tasks (wanted ≥0/≥0)
- **Please remind me of and can you invite mr. Chen for a meeting next Monday 6:00pm?** — event+event: got 1 events, 0 tasks (wanted ≥2/≥0)
- **On Febuary 14th make dinner reservations at the restaurant and tHIS IS IMPORTANT EVENT, PL** — event+event: got 1 events, 0 tasks (wanted ≥2/≥0)
- **Please give me notice when I need to leave for the conference** — medium: got 0 events, 0 tasks (wanted ≥0/≥0)
- **hey siri make sure my calendar is completely clear tomorrow** — medium: got 1 events, 0 tasks (wanted ≥0/≥0)
- **remind me in 50minutes and also please add calendar event** — event+event: got 1 events, 0 tasks (wanted ≥2/≥0)
- **add new event to calendar and name as anna, and then Please add event in calendar** — event+event: got 1 events, 0 tasks (wanted ≥2/≥0)
- **Make a new list of dog breeds. Also, Create a new list, please** — task+task: got 0 events, 1 tasks (wanted ≥0/≥2)
- **Remind me at this time. Also, create appointment to list** — event+task: got 1 events, 0 tasks (wanted ≥1/≥1)
- **Make a list of camera photos and i need a list of my clients today, make one** — task+task: got 1 events, 1 tasks (wanted ≥0/≥2)
- **Please remind me to call mom in half an hour and add coffee to the grocery list** — event+task: got 0 events, 2 tasks (wanted ≥1/≥1)
- **Open calendar.  Set event, and then Can you please create a list for me** — event+task: got 0 events, 1 tasks (wanted ≥1/≥1)
- **Remind me when it is lunchtime, and then I need oranges added to my grocery list.** — event+task: got 0 events, 1 tasks (wanted ≥1/≥1)
- **Open up a new list and add a Tab to the shopping list** — task+task: got 0 events, 1 tasks (wanted ≥0/≥2)
- **For the next three Sundays remind me I have yoga class at noon, and then yashas bithday wi** — event+event: got 1 events, 0 tasks (wanted ≥2/≥0)
- **I would like to start a new list, and then Put pencil on a new grocery list** — task+task: got 0 events, 1 tasks (wanted ≥0/≥2)
- **Remind me every Monday to take out the trash. Also, PUT MILK ON MY SHOPPING LIST** — event+task: got 0 events, 2 tasks (wanted ≥1/≥1)
- **add 'new year's eve' to calendar** — simple: got 0 events, 0 tasks (wanted ≥0/≥0)
- **Could you add this on my calender please and also alexa update my list with shoes** — event+task: got 0 events, 0 tasks (wanted ≥1/≥1)
- **Tell me when my next meeting is.** — medium: got 0 events, 0 tasks (wanted ≥0/≥0)

## Comparison

- 100 shared prompts (2899 only in A, 0 only in B)
- count-correct rate: 70% → 78%
- **5 got worse**, **14 got better**, 64 still pass, 17 still fail

### Got worse

- REMIND ABOUT OF ALL EVENT IN CALENDERS
- reopen groceries and add milk. Also, put xxx on the list
- add 'new year's eve' to calendar
- Make a list of camera photos and i need a list of my clients today, make one
- On Febuary 14th make dinner reservations at the restaurant and tHIS IS IMPORTANT EVENT, PLZ NOTE ON 

### Got better

- Olly remind me about the picnic at Regent park — and add paper towels to the grocery list.
- Remind me of the following event:. Also, Create shopping list for Target
- add date and time in calender with these people. Also, Calendar event. send invite, Bill Malinda
- 'exhibition 2017 mass' on Mar 25 make a note of it on the corresponding date and also remind me afte
- Send me a reminder to pick up my dog from the groomer at 1pm — and i need to add water to my Kroger 
- create repeating event 'john's birthday' on calendar. Also, Add reminder today evening to collect th
- I have an appointment tommorrow, remind me — and make a new list for me
- I need to add water to my Kroger list and add v8 to my groceries.
- Please alert me on Friday at 8:00 am to go to the gym and schedule meeting with Laura
- Begin new list of lottery numbers
- PDA please update list with new item
- start a new list and add grocery shopping to today's to-do list.
- include meeting in the list
- Set me a reminder for the get-together with the women's club on Sunday after church.