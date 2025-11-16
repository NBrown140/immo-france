

# Main Idea

## Problem
When searching for a house to buy/rent in France, we need to first know where we want to search, then use a website like SeLoger to find listings in that area. We can then filter by parameters such as prixe, number of rooms, etc. This is problem because:
1. The area which I am considering for my search could be very large. In that case, I need to manually go check many listings. I would like to be able to seach large areas in a data-driven way.
2. The parameters by which we filter are extremely basic. Purchasing a house can be a family's largest lifetime purchase. It should be well-informed. There are so many factors when cosidering the location of a house that are never taken into account, such as: air pollution, noise pollution, flood risk, drought risk, climate, cliamte change risk, internet/mobile conectivity, etc.

It is my hypothesis that if homebuyers (and maybe even renters) could access such data in a useful way, they would make great use of it. Obviously, real estate investors would be interested in this too.

## Solution
### Angle 1
A web application where users can search all avaialble real estate and cross-reference with data to make actually useful filters.

Users would also have the ability to explore historical sale prices and check if the house they are considering is good value or not. Especially given the additional risks that many people may ignore like flood risk, climate change risks, etc.

### Angle 2
Take the angle that purchasing a house is fundamentally a trade-off between what you value and what your budget is. Therefore, understanding what the user values is critical to making the correct trade-off.

My thesis: Everyone wants the same pefect house, but when budget constraints are applied, the decision is more complex and values become extremely important.

A web/mobile application where the user is guided through a set of steps where we:
1. Ask questions about what they value in a house. Always frame it as tradeoffs. For example, if you can assign only 10 points, how many do you assign to good lighting vs energy efficiency?
2. Create a "value set" for this customer, which is used to search for potential interesting homes.
3. Homes are proposed over time. Can also use some kind of feedback from user to fine-tune results (a bit like a true real estate agent would do).
4. We provide information about the house with full analysis of all our criteria and also some valuing metrics (i.e. is the house a good deal according to past sales)

Could be viewed as a full replacement of real estate agents via the use of powerful search algo and AI to give a human experience/interface.

### Data layers

Filtering layers:
- Air pollution: https://claude.ai/share/51ae472f-cf66-44f2-8027-11bb93f14440
- Noise pollution (https://www.data.gouv.fr/datasets/cartes-du-bruit/, https://www.bruitparif.fr/cartes-de-bruit/, https://meersens.com/les-cartes-de-bruit-en-france/)
- Walk score
- Distance from school, hospital, firefighter, etc.
- Climate: Yearly sun-days, too hot, too cold, too wet, too dry, etc.
- Environmental risks (https://www.georisques.gouv.fr/):
    - Flood risk
    - Drought risk
    - Wildfire risk
    - Landslide risk
    - Climate change risk additional risk
- Sunlight and shading from surroundings
- Solar panel potential
- Viewscape modelling
- Internet/Mobile connectivity (https://www.data.gouv.fr/datasets/mon-reseau-mobile/, )
- Crazy ideas:
    - Visual "beauty":
      - Use dashcam dataset like [OSV5M](https://huggingface.co/datasets/osv5m/osv5m/tree/main) and label with visual beauty. Train model to predict beauty from pictures. Make a map of landscape beauty.
      - Same but for images of the house. Train algo to predict beauty.


Historical sale prices can be obtained at https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres/


## Competition

Real estate pricing
- PriceHubble: https://www.pricehubble.com/

Real Estate marketplaces
- SeLoger
- LeBonCoin


## Geocoding

Geocoding can be done via paid APIs like Google Maps or can be self-hosted using OSM data. The self hosted options I found are:
- Photon (Komoot): https://github.com/komoot/photon
- Pelias: https://github.com/pelias/docker
- Nominatim: https://github.com/mediagis/nominatim-docker

Nominatim seems to be the easiest to setup using docker:
```
docker run -it \
  -e PBF_URL=https://download.geofabrik.de/europe/france/rhone-alpes-251103.osm.pbf \
  -v ~/tmp/nominatim-flatnode:/nominatim/flatnode \
  -p 8080:8080 \
  --name nominatim \
  mediagis/nominatim:5.1
```

```
docker run -it \
  -e PBF_URL=https://download.geofabrik.de/europe/france-latest.osm.pbf \
  -e REPLICATION_URL=https://download.geofabrik.de/europe/france-updates/ \
  -e NOMINATIM_FLATNODE_FILE=/nominatim/flatnode/flatnode.file \
  -e IMPORT_STYLE=address \
  -v ~/tmp/nominatim/nominatim-flatnode:/nominatim/flatnode \
  -v ~/tmp/nominatim/nominatim-postgres:/var/lib/postgresql/16/main \
  -p 8080:8080 \
  --shm-size=2g \
  --name nominatim \
  mediagis/nominatim:5.1
```
This requires 100+ GB of storage. Be sure this is available on your system and that docker desktiop is given sufficient storage space.

Test with:
`http://localhost:8080/search.php?street=17%20claudius%20chappaz&city=annecy&country=france&postalcode=74960`
`http://localhost:8080/search.php?q=avenue%20pasteur`

## Development environment

The Python tooling is managed by [uv](https://docs.astral.sh/uv/), which keeps dependencies reproducible via `pyproject.toml` and `uv.lock`.

1. Install uv if needed (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `pip install uv`).
2. Create the local virtual environment with the runtime dependencies:
   ```bash
   uv sync
   ```
   This produces a `.venv` folder that uv automatically reuses.
3. Add notebook helpers when you want to work inside the `.ipynb` files:
   ```bash
   uv sync --group notebooks
   ```
4. Run scripts or notebooks through uv so the correct interpreter is used:
   ```bash
   uv run python valeurs_historique.py          # run the geocoding helper
   uv run jupyter lab                           # open the notebooks
   ```
5. When dependencies change, run `uv lock` (or simply `uv sync`) to refresh the lockfile before committing.
