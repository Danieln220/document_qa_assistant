# Demo facts: Ridgeline Equipment Rentals (fictional)

Internal cheat sheet for the demo and the eval set. It is **not** ingested, because it
lives outside `documents/`. It records the key facts planted in the documents, and the
topics that are **deliberately missing** so the assistant has to refuse them.

## Company
- Ridgeline Equipment Rentals, LLC. Boise, Idaho. Three branches: Boise Main Yard, Nampa, Twin Falls.
- 24/7 breakdown hotline (208) 555-0199. Main counter (208) 555-0142.

## Key planted facts (document -> fact)
- Rental Agreement: late return = 1.5x daily rate for each day or part-day late, after a 59-minute grace period.
- Rental Agreement: EX-35 mini excavator daily rate $385. So 2 days late = 2 x 1.5 x $385 = $1,155.
- Returns & Damages Policy (scanned): $35 late-return administration fee per contract, on top of late charges.
- Rental Agreement: fuel. Equipment leaves full. Refuelling is charged at $6.25/gal gasoline or $7.50/gal diesel, plus a $25 refuelling service fee. The GN-7500 generator runs on gasoline.
- Returns & Damages Policy: cleaning fee $75 standard, $150 for excavators and skid steers.
- Returns & Damages Policy: disputes must be in writing within 5 business days of the inspection report.
- Rental Agreement: Damage Waiver = 12% of rental charges, $500 deductible.
- Maintenance Manual: EX-35 hydraulic oil change every 1,000 engine hours or 12 months, whichever comes first.
- Maintenance Manual: EX-35 engine oil every 250 hours. GN-7500 oil every 100 hours.
- Maintenance Manual: red tag = do not rent.
- Employee Handbook: vacation is 10 days (years 1-2), 15 days (years 3-5), 20 days (6+). 6 sick days.
- Branch FAQ: Twin Falls is closed on Saturdays.

## Deliberately missing (the assistant must refuse)
- Parental / maternity / paternity leave (the Handbook covers vacation, sick, bereavement and jury duty only).
- Retirement plan / 401(k) match.
- Selling used equipment.
- Cranes (not in the fleet).
- Wi-Fi passwords.
