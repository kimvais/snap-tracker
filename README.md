# Snap-tracker

A collection & game tracker for [Marvel Snap](https://marvelsnap.com).

Work in progress.

## Installation

```PowerShell
pip install snap-tracker
```

## Usage
```text
snap-tracker (card_stats|upgrades)
```
Other commands are not in useful state, but you can see them with `snap-tracker help`. Use them at your own risk.

### Card stats
To show all cards in your collection based on their performance ranked by the values found in `AccountState` 
under `['Account']['CardStats']`:
```powershell 
snap-tracker card_stats
```

![Screenshot of output of snap-tracker card_stats](https://github.com/kimvais/snap-tracker/blob/master/doc/screenshot_card_stats.png?raw=true)

### Upgrades

To show the cards in your collection for which you have enough boosters and credits to upgrade:

```PowerShell
snap-tracker upgrades
```

![Screenshot of output of snap-tracker upgrades](https://github.com/kimvais/snap-tracker/blob/master/doc/screenshot_upgrades.png?raw=true)

_The author of this project is not affiliated with MARVEL, NuVerse or Second Dinner._
