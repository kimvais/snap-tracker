# Snap-tracker

A collection & game tracker for [Marvel Snap](https://marvelsnap.com).

Work in progress.

## Installation

```PowerShell
pip install snap-tracker
```

## Usage
```text
snap-tracker (card_stats|parse_game_state|upgrades)
```
* `snap-tracker card_stats` shows all cards in your collection based on their performance ranked by the values found in `AccountState` under `['Account']['CardStats']`
* `snap-tracker upgrades` will show you cards in your collection hat you have enough boosters and credits to upgrade


![Screenshot of output of snap-tracker upgrades](https://github.com/kimvais/snap-tracker/blob/master/doc/screenshot_upgrades.png?raw=true)

_The author of this project is not affiliated with MARVEL, NuVerse or Second Dinner._
