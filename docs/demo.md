# Demo and pitch

## One line

A handheld radar that finds people through walls and reads their breathing and heart rate from arm's length,
for rescuers searching homes after a hurricane.

## Setup at the table

- A drywall or foam-board panel at the table edge, a chair behind it.
- One teammate seated behind the panel (warm up the C1001 on them before the judge arrives).
- Pulse in front, running live, gate set to 2 to 3 m so the crowd doesn't show up.
- Laptop with the command dashboard open (if built). Sim mode ready as backup.

## Script (3 minutes)

1. **Hook, 20 s.** After a hurricane, rescuers search collapsed homes by shouting and listening.
   NASA built a radar that finds heartbeats under rubble. We built a handheld version for about $170.
2. **Find, 40 s.** Hand the judge Pulse. A dot is already sitting behind the panel.
   A second teammate walks across the room: a second dot moves. "That's through the wall."
3. **Lock on, 40 s.** Judge taps the hidden dot: "get within 1.5 m." Judge leans over and aims.
   Breathing and heart rate lock in, the dot turns amber: still, breathing, reach them first.
4. **Flip it, 30 s.** The judge sits behind the panel. Their own dot appears; aim at them and their own
   heart rate shows up. This is the moment they remember.
5. **Hard parts, 30 s.** Fusing two radars that disagree; finding still people when the tracking radar wants
   movement; two binary serial protocols at 256000 and 115200 baud; gating out a crowded hall.
6. **Honest close, 20 s.** Sees through drywall and debris, not concrete; a real unit would use lower-frequency
   radar. Next: drop-in sensor nodes that mesh with no cell service. Show the AI sitrep if built.

## Claims we can make

- Tracks up to 3 people within about 6 m, including through thin walls (drywall, wood, plastic, foam).
- Reads breathing and heart rate without contact from up to 1.5 m.
- Separates moving people from still-but-breathing people, the ones rescuers should reach first.
- Precedent: NASA JPL and DHS's FINDER microwave radar helped find four men trapped under rubble after the
  2015 Nepal earthquake and has detected heartbeats through 30 ft of rubble in tests.
  ([JPL](https://www.jpl.nasa.gov/news/finder-search-and-rescue-technology-helped-save-lives-in-nepal/),
  [DHS](https://dhs.gov/archive/science-and-technology/news/2015/05/05/finder-helps-save-four-nepal))

## Claims we must not make

- "Works through rubble" or "through concrete."
- Medical-grade vitals, diagnosis, or anything based on heart-rate thresholds (sensor clamps to 60 to 100).
- Any statistic we haven't looked up and can cite.
