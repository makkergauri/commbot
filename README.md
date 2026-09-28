
Use a spare phone and SIM. That app can read every SMS the phone receives, including bank OTPs. CommBot ignores anything that isn't a mobile number, but the permission is still on the device.

---

## The control room

Five pages, server-rendered, no JavaScript, so it loads on a weak connection:

- **Overview**: what needs approving, a map of live warnings, breakdown by hazard
- **Alerts**: everything current, filterable
- **Coverage**: which districts are covered and in which language
- **Activity**: the delivery log, with numbers part-hidden
- **How it works**: the explanation, for anyone arriving cold

Approve buttons show the exact Hindi and English text that will be sent before you approve it.

---

## What real data taught me

Most of the work wasn't the pipeline, it was the mess the real feed contains.

**The area field is often useless.** Real values include `some parts`, `9 districts of Gujarat`, `6 Mandals` and `MOD TSRA`, which is aviation shorthand for thunderstorm with rain, not a place. Each needed its own rule, and where no area can be matched, CommBot logs the alert rather than pretending it can target it.

**Identifiers lie.** The feed's item id is `1789916877126017`; the alert inside it is `IN-1789916877126017_17`. I assumed they matched, which meant re-downloading every alert on every poll against a government server, invisibly, forever.

**Geometry can be absurd.** One alert carried 64,472 boundary points. They're now thinned to 400, which loses nothing at district scale.

**The bug only a phone could find.** After days of testing against the console, the first real SMS arrived at 8:28 for a warning valid until 8:30. Every layer was correct and the message was useless. CommBot now refuses to push anything with under fifteen minutes left, and there's a test named after it.

---

## Limitations

- **Hindi and English only**, and the Hindi is pending independent review.
- **Place names come from a small hand-written list**, so Hindi messages still show some district names in Latin script.
- **Polygon fetching is capped** at 25 per cycle to be gentle on the government server, so some alerts are targeted by district name only.
- **A single SIM can't serve a district.** Indian prepaid plans typically cap around 100 SMS a day. Real deployment means DLT registration and a bulk provider.
- **No voice line.** An IVR version existed early on, then was removed when the project moved off Twilio.
- **No formal evaluation yet.** I know it delivers correct messages; I don't know whether they help, and only a pilot would answer that.

---

## Next

- Bengali, Tamil, Marathi and Telugu, each reviewed by a native speaker before release
- Independent review of the existing Hindi phrases
- Automatic transliteration of place names
- Central Water Commission river-level data as a second source
- A pilot with a district authority or NGO, which is the only real test of whether this helps

---

## Credits and licence

Alerts come from NDMA's SACHET platform, published by IMD, the Central Water Commission and state disaster management authorities. CommBot relays official warnings; it never issues its own. The India boundary is from [DataMeet's](https://github.com/datameet/maps) open map, CC-BY.


MIT licensed.
