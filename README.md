# cartera-nav-fondos

Actualiza automáticamente, una vez al día, el NAV (valor liquidativo) de dos
fondos institucionales de BlackRock/iShares que no tienen API pública ni
cotizan en bolsa:

- **iShares Developed World Index Fund (IE) S Acc EUR** — ISIN `IE000ZYRH0Q7`
- **iShares Emerging Markets Index Fund (IE) S Acc EUR** — ISIN `IE000QAZP7L2`

El resultado se guarda en [`nav_fondos.json`](nav_fondos.json), que la app
[Cartera](https://github.com/halecs8) lee directamente en tiempo real vía
`fetch()` a este archivo en `raw.githubusercontent.com` — no hace falta
redesplegar la app cuando el NAV cambia.

## Cómo funciona

Un [GitHub Action](.github/workflows/actualizar-nav.yml) programado (cron,
todos los días a las 06:00 UTC) ejecuta
[`actualizar_nav_fondos.py`](actualizar_nav_fondos.py), que abre cada página
de producto de BlackRock con un navegador headless (Playwright — hace falta
porque el NAV se renderiza con JavaScript, BlackRock no ofrece una API), lee
el bloque "Valor liquidativo" de la cabecera, y si todo va bien hace commit
del `nav_fondos.json` actualizado.

Si la extracción falla (por ejemplo, BlackRock cambia el maquetado de la
página), el script termina con error **sin tocar `nav_fondos.json`** — verás
el job en rojo en la pestaña *Actions* de este repo, y GitHub te avisará por
email automáticamente al dueño del repositorio.

## Ejecutarlo manualmente

Desde la pestaña **Actions** de este repo → *Actualizar NAV fondos
BlackRock* → *Run workflow*. También puedes ejecutarlo en tu propio
ordenador:

```bash
pip install playwright
playwright install chromium
python actualizar_nav_fondos.py
```
