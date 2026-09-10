# Decisions

## What I built

**A clean copy of the data.** One command reads Kestrel's database without changing it and builds a cleaned copy. Every row left out or corrected is logged with the reason: for example, 41,401 cancelled or open orders left out, and 900 negative return quantities corrected.

**One screen, five numbers:** fill rate, on-time-in-full, returns, stock near expiry, and temperature breaches on chilled deliveries. The worst performers are listed straight away. Every number states what it is based on: period, region, unit, what was excluded, and how many records. Region and period sit in the page address, so a regional manager can bookmark their own view.

**A data quality page** showing what each number leaves out and why, down to the individual records. When two people's numbers differ, the question becomes "which rule did you apply differently?", not "who is right?".

**A chatbot ("Ask anything")** for plain-English questions:
- **Simple questions** get one direct answer.
- **"Why" questions start a short investigation.** Asked "why did fill rate drop in the West last week?", it checks that week, then the week before, then breaks the change down. It picks each step after seeing the last, up to six.
- **You watch it work.** Steps appear as they happen, and the answer lists the measurements behind it.
- **Follow-ups work.** "And the South?" builds on the previous question; it remembers the last ten.
- **It follows the dashboard's region and period,** and declines what the data can't answer, such as forecasts.
- **It can't make up numbers.** The AI calculates nothing: every figure comes from the dashboard's own code, and any sentence quoting a number it wasn't given is thrown away.
- **Trying it live shaped it.** It once described a small rise as a drop, and compared a full week with a two-day one. Both are fixed. Asked the leading "why did it drop" on the real data, it now answers that it didn't.

## What I deliberately did not build

- **Freight cost per case.** Carrier invoices can't be matched to deliveries, so the cost has to be split by a method Finance agrees, not one I invent.
- **Competitor price comparison.** Competitor product names can't be reliably matched to Kestrel's products, and a wrong price gap is worse than the WhatsApp group.
- **Login and permissions** (the region filter is a convenience, not security), and **frontend automated tests**.

## What I assumed

- **Eaches, not cases.** Modern trade penalises units short, so eaches is the default; cases is one click away. Both come from the same records, so they can't disagree: 85.6% and 85.9% for FY27 Q1.
- **Q1 on the front page.** The page opens on the latest finished quarter with data: FY27 Q1.
- **On-time-in-full shows 0%, correctly.** Not one order line was delivered in full. I didn't loosen the definition to flatter the number. On-time alone (43%) is still useful, and why nothing is ever recorded as complete is a question for Operations.
- **No service agreement is written down,** so "on time" allows 30 minutes and "near expiry" means 30 days. Both are settings.
- **Where the source contradicts itself, I recalculate.** Recorded delay disagrees with arrival times on 87% of deliveries, so delay comes from the times. Only approved credit notes count as money lost, and damaged or blocked stock isn't available.
- **Duplicate and test outlets are left out.** Duplicates match on GST number, since matching on name would drop 197 real shops. Test outlets are found by their "TST" code, because all are marked active.
- **The chatbot may suggest a cause it can't measure.** That explanation is the useful part. Its measurements sit beside it so you can judge.

## With two more weeks

Freight cost once Finance agrees the split. Competitor prices using a hand-checked list of product matches. A shareable link to a chatbot investigation. A set of real questions to test the chatbot automatically, since its bugs so far were found live.

## What breaks first in production

- **The rebuild:** it starts from scratch each time, which is seconds today and too slow at 100 times the data.
- **The database:** SQLite suits one machine, not many users at once.
- **Chatbot cost:** a "why" question takes about six AI calls and 15–25 seconds, so cost and rate limits appear once every manager uses it.
- **Thinly tested rules:** the duplicate-outlet rule had only two examples to check against.
