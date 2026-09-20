# Dataset run score — `/var/folders/0f/nk3dnvrd54jbjz_qn40_ynwh0000gn/T/engine_compare_403h15na/engine_run.db`

- product-adjusted count-correct **85%** (3 overridden rows; raw below is the comparable number)
- **100 prompts** scored · count-correct **83%** · garbage-title rate **0%**
- total_ms p50 60 · p95 44745
- parse paths: {'deep': 58, 'fast': 42}

## By complexity

| Tier | n | count-correct | garbage titles | total_ms p50 |
|---|---:|---:|---:|---:|
| simple | 34 | 97% | 0% | 32 |
| medium | 33 | 85% | 0% | 46 |
| complex | 33 | 67% | 0% | 87 |

## By compound kind

| Kind | n | count-correct | garbage titles | dates collapsed |
|---|---:|---:|---:|---:|
| event+event | 11 | 82% | 0% | 45% |
| task+task | 11 | 55% | 0% | 0% |
| event+task | 11 | 64% | 0% | 18% |

## event+task: which half goes missing when it fails

- both present: 7 · event missing: 2 · task missing: 2 · both missing: 0

## Correctness by parse path

| Path | count-correct |
|---|---:|
| deep | 72% |
| fast | 98% |

## Count-mismatch failures (17)

- **reopen groceries and add milk. Also, put xxx on the list** — task+task: got 1 events, 1 tasks (wanted ≥0/≥2)
- **Please remind me of and can you invite mr. Chen for a meeting next Monday 6:00pm?** — event+event: got 1 events, 0 tasks (wanted ≥2/≥0)
- **The list should not contain all food items with the prefix dry.** — medium: got 1 events, 0 tasks (wanted ≥0/≥0)
- **On Febuary 14th make dinner reservations at the restaurant and tHIS IS IMPORTANT EVENT, PL** — event+event: got 1 events, 0 tasks (wanted ≥2/≥0)
- **Please give me notice when I need to leave for the conference** — medium: got 0 events, 0 tasks (wanted ≥0/≥0)
- **hey siri make sure my calendar is completely clear tomorrow** — medium: got 1 events, 0 tasks (wanted ≥0/≥0)
- **is today st. patricks day** — simple: got 1 events, 0 tasks (wanted ≥0/≥0)
- **Remind me at this time. Also, create appointment to list** — event+task: got 2 events, 0 tasks (wanted ≥1/≥1)
- **Make a list of camera photos and i need a list of my clients today, make one** — task+task: got 1 events, 1 tasks (wanted ≥0/≥2)
- **Please remind me to call mom in half an hour and add coffee to the grocery list** — event+task: got 0 events, 2 tasks (wanted ≥1/≥1)
- **PDA do i have any appointments set for tomorrow?** — medium: got 1 events, 0 tasks (wanted ≥0/≥0)
- **Open up a new list and add a Tab to the shopping list** — task+task: got 0 events, 1 tasks (wanted ≥0/≥2)
- **I would like to start a new list, and then Put pencil on a new grocery list** — task+task: got 0 events, 1 tasks (wanted ≥0/≥2)
- **Remind me every Monday to take out the trash. Also, PUT MILK ON MY SHOPPING LIST** — event+task: got 0 events, 2 tasks (wanted ≥1/≥1)
- **start a new list and add grocery shopping to today's to-do list.** — task+task: got 0 events, 1 tasks (wanted ≥0/≥2)
- **Could you add this on my calender please and also alexa update my list with shoes** — event+task: got 1 events, 0 tasks (wanted ≥1/≥1)
- **Tell me when my next meeting is.** — medium: got 0 events, 0 tasks (wanted ≥0/≥0)

## Comparison

- 100 shared prompts (2899 only in A, 0 only in B)
- count-correct rate: 70% → 83%
- **6 got worse**, **20 got better**, 63 still pass, 11 still fail

### Got worse

- is today st. patricks day
- Make a list of camera photos and i need a list of my clients today, make one
- On Febuary 14th make dinner reservations at the restaurant and tHIS IS IMPORTANT EVENT, PLZ NOTE ON 
- reopen groceries and add milk. Also, put xxx on the list
- The list should not contain all food items with the prefix dry.
- PDA do i have any appointments set for tomorrow?

### Got better

- 'exhibition 2017 mass' on Mar 25 make a note of it on the corresponding date and also remind me afte
- Remind me of the following event:. Also, Create shopping list for Target
- PDA please update list with new item
- I need to add water to my Kroger list and add v8 to my groceries.
- Olly remind me about the picnic at Regent park — and add paper towels to the grocery list.
- Begin new list of lottery numbers
- Please alert me on Friday at 8:00 am to go to the gym and schedule meeting with Laura
- include meeting in the list
- create repeating event 'john's birthday' on calendar. Also, Add reminder today evening to collect th
- Open calendar.  Set event, and then Can you please create a list for me
- Set me a reminder for the get-together with the women's club on Sunday after church.
- add new event to calendar and name as anna, and then Please add event in calendar
- remind me in 50minutes and also please add calendar event
- Make a new list of dog breeds. Also, Create a new list, please
- On the fifth of November, I need to go to Washington, D.C, and then I'd like to set a date for this 
- I have an appointment tommorrow, remind me — and make a new list for me
- add date and time in calender with these people. Also, Calendar event. send invite, Bill Malinda
- Send me a reminder to pick up my dog from the groomer at 1pm — and i need to add water to my Kroger 
- Remind me when it is lunchtime, and then I need oranges added to my grocery list.
- For the next three Sundays remind me I have yoga class at noon, and then yashas bithday with vinay ,