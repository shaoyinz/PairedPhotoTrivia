# Demo

A playable web demo: **https://shaoyinz.github.io/PairedPhotoTrivia/**

Maya and Theo are a made-up couple, and their trips are made up. The page shows the home screen
(trips found in both libraries), a five-photo round (map pin, then year, month and day), the reveal
with scoring from the PRD, and the owner's veto before a photo is sent back. Below the phone it
explains how trips are found and what syncs between the two phones.

It is a single static page: `index.html`, `map.json` and `photos/`. GitHub Pages deploys this
folder on every push to `main` that touches it (`.github/workflows/pages.yml`).

Run it locally (it fetches `map.json`, so open it over HTTP rather than as a file):

```bash
python3 -m http.server -d demo 8000   # then open http://localhost:8000
```

## Credits

These files are **not** covered by the repo's MIT license. Each keeps the license below; all were
resized.

The map in `map.json` is projected and simplified from [Natural Earth](https://www.naturalearthdata.com/)
(public domain).

| File | Photo | Author | License |
| --- | --- | --- | --- |
| `ice-hallgrims.jpg` | [View from Hallgrímskirkja](https://commons.wikimedia.org/wiki/File:View_from_Hallgr%C3%ADmskirkja_4.JPG) | Jakec | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) |
| `ice-jokuls.jpg` | [Jökulsárlón glacier lagoon](https://commons.wikimedia.org/wiki/File:J%C3%B6kuls%C3%A1rl%C3%B3n,_Iceland,_20240719_1142_2543.jpg) | Jakub Hałun | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `ice-kirkju.jpg` | [Kirkjufell](https://commons.wikimedia.org/wiki/File:Kirkjufell,_Iceland,_20240714_1631_0713.jpg) | Jakub Hałun | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `ice-reynis.jpg` | [Reynisfjara black sand beach](https://commons.wikimedia.org/wiki/File:Reynisfjara,_Iceland,_20230501_1641_4049.jpg) | Jakub Hałun | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `ice-skoga.jpg` | [Skógafoss](https://commons.wikimedia.org/wiki/File:Sk%C3%B3gafoss_Waterfall,_Iceland,_20240720_1318_2975.jpg) | Jakub Hałun | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `ice-x1.jpg` | [Harbor seal at Jökulsárlón](https://commons.wikimedia.org/wiki/File:021_Wild_smiling_harbor_seal_at_J%C3%B6kuls%C3%A1rl%C3%B3n_(Iceland)_Photo_by_Giles_Laurent.jpg) | Giles Laurent | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `ice-x2.jpg` | [Skógafoss](https://commons.wikimedia.org/wiki/File:Sk%C3%B3gafoss_Waterfall,_Iceland,_20240720_1330_2993.jpg) | Jakub Hałun | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `ice-x3.jpg` | [Reynisfjara](https://commons.wikimedia.org/wiki/File:Reynisfjara,_Su%C3%B0urland,_Islandia,_2014-08-17,_DD_164.JPG) | Diego Delso | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `lis-belem.jpg` | [Belém Tower](https://commons.wikimedia.org/wiki/File:Lisbon_Torre_de_Bel%C3%A9m_BW_2018-10-03_16-33-21.jpg) | Berthold Werner | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `lis-comercio.jpg` | [Praça do Comércio](https://commons.wikimedia.org/wiki/File:Lisbon_Pra%C3%A7a_do_Com%C3%A9rcio_BW_2018-10-08_17-42-58.jpg) | Berthold Werner | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `lis-pena.jpg` | [Pena Palace](https://commons.wikimedia.org/wiki/File:Sintra_Portugal_Pal%C3%A1cio_da_Pena-01.jpg) | CEphoto, Uwe Aranas | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) |
| `lis-roca.jpg` | [Cabo da Roca](https://commons.wikimedia.org/wiki/File:Cabo_da_Roca_-_Cape_Roca.JPG) | Ввласенко | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) |
| `lis-tram.jpg` | [Tram 28 by Lisbon Cathedral](https://commons.wikimedia.org/wiki/File:Tramway_place_Cath%C3%A9drale_Lisbonne_6.jpg) | Chabe01 | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `lis-x1.jpg` | [Belém Tower at night](https://commons.wikimedia.org/wiki/File:Torre_de_Bel%C3%A9m_por_Rodrigo_Tetsuo_Argenton_(2).jpg) | Rodrigo.Argenton | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `lis-x2.jpg` | [Praça do Comércio from the river](https://commons.wikimedia.org/wiki/File:View_of_Pra%C3%A7a_do_Com%C3%A9rcio_from_the_Tagus_River_in_Lisbon,_20250604_2038_9656.jpg) | Jakub Hałun | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `lis-x3.jpg` | [Cliffs at Cabo da Roca](https://commons.wikimedia.org/wiki/File:Cliffs_at_Cabo_da_Roca,_Portugal,_20250606_1522_0263.jpg) | Jakub Hałun | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| `sur-bixby.jpg` | [Bixby Creek Bridge](https://commons.wikimedia.org/wiki/File:Bixby_Creek_Bridge_2013.jpg) | Tuxyso | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) |
| `sur-lobos.jpg` | [Point Lobos](https://commons.wikimedia.org/wiki/File:Point_Lobos_September_2012_013.jpg) | King of Hearts | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) |
| `sur-mcway.jpg` | [McWay Falls](https://commons.wikimedia.org/wiki/File:McWay_Falls_Big_Sur_May_2011_002.jpg) | King of Hearts | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) |
| `sur-monterey.jpg` | [Old Fisherman's Wharf](https://commons.wikimedia.org/wiki/File:Fisherman%27s_Wharf_Monterey_September_2013_007.jpg) | King of Hearts | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `sur-pfeiffer.jpg` | [Keyhole Arch, Pfeiffer Beach](https://commons.wikimedia.org/wiki/File:Pfeiffer_Beach_at_Dusk_(Unsplash).jpg) | Kace Rodriguez | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `sur-x1.jpg` | [McWay Falls](https://commons.wikimedia.org/wiki/File:McWay_Falls_Big_Sur_September_2012_001.jpg) | King of Hearts | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `sur-x2.jpg` | [Point Lobos](https://commons.wikimedia.org/wiki/File:Point_Lobos_September_2012_007.jpg) | King of Hearts | [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/) |
| `sur-x3.jpg` | [Monterey harbor](https://commons.wikimedia.org/wiki/File:Fisherman%27s_Wharf_Monterey_September_2013_001.jpg) | King of Hearts | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
