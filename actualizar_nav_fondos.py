"""
Extrae el NAV (valor liquidativo) diario de dos fondos institucionales de
BlackRock/iShares directamente de su página pública de producto, y lo
guarda en nav_fondos.json.

    - iShares Developed World Index Fund (IE) S Acc EUR — IE000ZYRH0Q7
    - iShares Emerging Markets Index Fund (IE) S Acc EUR  — IE000QAZP7L2

POR QUÉ ASÍ: son clases institucionales de un fondo mutuo irlandés (UCITS),
no ETFs cotizados — BlackRock no ofrece una API pública para su NAV. El
valor solo aparece renderizado por JavaScript en la cabecera de la página
de producto ("Valor liquidativo a <fecha>"), por eso se usa un navegador
headless (Playwright) en vez de una petición HTTP simple.

Selectores usados (verificados manualmente contra la página real en jul 2026):
    li[data-col="fundHeader.fundNav.navAmount"]        -> NAV + fecha
    li[data-col="fundHeader.fundNav.navAmountChange"]  -> variación + %
    .product-data-item.col-isin .data                  -> ISIN de la página,
        usado para verificar que corresponde al fondo esperado antes de
        aceptar el dato.

Si BlackRock cambia el maquetado y estos selectores dejan de encontrarse (o
el ISIN de la página no coincide con el esperado), el script termina con
error y código de salida distinto de cero SIN escribir nav_fondos.json —
mejor un job en rojo en GitHub Actions (que avisa por email) que dejar la
app leyendo un NAV obsoleto o inventado.

INSTALACIÓN (una sola vez, solo si lo ejecutas en tu propio ordenador):
    pip install playwright
    playwright install chromium

USO:
    python actualizar_nav_fondos.py
    -> genera/actualiza nav_fondos.json en el mismo directorio

En producción esto lo ejecuta automáticamente GitHub Actions una vez al día
(ver .github/workflows/actualizar-nav.yml), no hace falta correrlo a mano.

AVISO: esto lee una página pública sin autenticarse ni evitar ningún control
de acceso, una vez al día. Aun así es una automatización no oficial sobre la
web de BlackRock: si cambian el maquetado, el script fallará de forma
explícita (ver arriba) y habrá que ajustar los selectores. Para un uso
productivo/comercial más serio, lo fiable de verdad es una fuente de datos
de pago con cobertura de fondos (p.ej. EOD Historical Data).
"""

import json
import re
import sys
from datetime import datetime, timezone

from playwright.sync_api import sync_playwright

FONDOS = {
    "IE000ZYRH0Q7": {
        "nombre": "iShares Developed World Index Fund (IE) S Acc EUR",
        "url": "https://www.blackrock.com/es/profesionales/productos/345277/ishares-developed-world-index-fund-ie",
    },
    "IE000QAZP7L2": {
        "nombre": "iShares Emerging Markets Index Fund (IE) S Acc EUR",
        "url": "https://www.blackrock.com/es/profesionales/productos/345276/ishares-emerging-markets-index-fund-ie",
    },
}

OUTPUT_FILE = "nav_fondos.json"

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}


def parse_fecha_es(texto):
    """'Valor liquidativo a 27 jul 2026' -> ('2026-07-27', '27 jul 2026')"""
    m = re.search(r"(\d{1,2})\s+([a-záéíóú]{3,4})\.?\s+(\d{4})", texto.lower())
    if not m:
        return None, None
    dia, mes_txt, anio = m.groups()
    mes = MESES.get(mes_txt[:3])
    if not mes:
        return None, None
    iso = f"{int(anio):04d}-{mes:02d}-{int(dia):02d}"
    etiqueta = texto.split(" a ", 1)[-1].strip()
    return iso, etiqueta


def parse_decimal_es(texto):
    """'EUR 11,99' -> 11.99 ; '0,03' -> 0.03 ; '-1,20' -> -1.2"""
    m = re.search(r"-?\d[\d.]*,\d+|-?\d+", texto.replace("\xa0", " "))
    if not m:
        return None
    return float(m.group(0).replace(".", "").replace(",", "."))


def extraer_nav(page, isin_esperado):
    nav_li = page.locator('li[data-col="fundHeader.fundNav.navAmount"]').first
    cambio_li = page.locator('li[data-col="fundHeader.fundNav.navAmountChange"]').first
    isin_el = page.locator(".product-data-item.col-isin .data").first

    nav_li.wait_for(state="attached", timeout=20000)

    isin_pagina = isin_el.inner_text().strip() if isin_el.count() else None
    if isin_pagina != isin_esperado:
        raise RuntimeError(
            f"el ISIN de la página ({isin_pagina!r}) no coincide con el "
            f"esperado ({isin_esperado!r}) — puede que BlackRock haya "
            f"cambiado la URL o el maquetado del fondo"
        )

    nav_label = nav_li.locator(".header-nav-label").inner_text()
    nav_data = nav_li.locator(".header-nav-data").inner_text()
    cambio_data = cambio_li.locator(".header-nav-data").inner_text() if cambio_li.count() else ""

    fecha_iso, fecha_label = parse_fecha_es(nav_label)
    divisa_m = re.search(r"[A-Z]{3}", nav_data)
    divisa = divisa_m.group(0) if divisa_m else None
    nav = parse_decimal_es(nav_data)

    importe_m = re.search(r"[A-Z]{3}\s*(-?[\d.,]+)", cambio_data)
    variacion_importe = parse_decimal_es(importe_m.group(1)) if importe_m else None
    pct_m = re.search(r"\(([-\d.,]+)\s*%\)", cambio_data)
    variacion_pct = parse_decimal_es(pct_m.group(1)) if pct_m else None

    if nav is None or fecha_iso is None:
        raise RuntimeError(
            f"no se pudo interpretar el NAV/fecha del texto de la página "
            f"(label={nav_label!r}, data={nav_data!r})"
        )

    return {
        "isin": isin_esperado,
        "divisa": divisa,
        "nav": nav,
        "variacion_importe": variacion_importe,
        "variacion_pct": variacion_pct,
        "fecha_nav": fecha_iso,
        "fecha_nav_label": fecha_label,
    }


def main():
    resultados = {}
    errores = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="es-ES")

        for isin, info in FONDOS.items():
            print(f"Consultando {isin} ({info['nombre']})...")
            try:
                page.goto(info["url"], wait_until="domcontentloaded", timeout=30000)
                try:
                    page.click("#onetrust-reject-all-handler", timeout=5000)
                except Exception:
                    pass  # banner de cookies ya resuelto o no presente

                datos = extraer_nav(page, isin)
                datos["nombre"] = info["nombre"]
                resultados[isin] = datos
                print(f"  -> NAV {datos['nav']} {datos['divisa']} ({datos['fecha_nav_label']})")
            except Exception as e:
                print(f"  -> ERROR: {e}", file=sys.stderr)
                errores.append(f"{isin}: {e}")

        browser.close()

    if errores:
        # No sobreescribir nav_fondos.json con datos parciales o incorrectos:
        # si algo falló es preferible que el job de GitHub Actions quede en
        # rojo (avisa por email al dueño del repo) a que la app se quede
        # leyendo un NAV desactualizado sin que nadie se entere.
        print("\nHubo errores — nav_fondos.json NO se ha modificado.", file=sys.stderr)
        sys.exit(1)

    salida = {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fondos": resultados,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    print(f"\nGuardado en {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
