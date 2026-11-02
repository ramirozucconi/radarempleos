# Radar de Empleos: recolector

Script que corre solo dos veces por día en GitHub y junta avisos de empleo de:

- **~70 empresas, directo de sus sistemas de reclutamiento** (Greenhouse, Ashby, Lever y Workday): Anthropic, OpenAI, Stripe, Coinbase, Kraken, ElevenLabs, Adyen, Dow, Assurant, Chevron y más.
- **Bolsas de empleo remoto:** Remotive, Himalayas, Get on Board y We Work Remotely.

Después filtra y ordena los avisos según tu perfil:

- **Roles que sirven:** procurement, P2P, cuentas a pagar, billing, BA, BI/Data, SAP y similares.
- **Ubicación:** Argentina, LATAM, UE o remoto global.
- **Descartes:** ventas, ingeniería, junior y avisos de más de 30 días.
- **Puntaje:** según las palabras de tu CV que aparecen en el aviso (SAP, Ariba, Power BI, SQL, proveedores, facturas…).

El resultado queda en la carpeta `data/`:

| Archivo | Qué tiene |
|---|---|
| `candidates.json` | Los avisos que pasaron el filtro, ordenados por puntaje. `is_new: true` marca los que aparecieron en la última corrida. |
| `report.md` | El mismo listado en una tabla legible desde GitHub. |
| `sources_report.json` | Qué fuentes funcionaron y cuáles dieron error. |
| `seen.json` | Memoria interna para saber qué avisos ya se vieron. |

El radar de Claude lee `candidates.json`, evalúa en detalle los mejores y los carga en tu Radar de Empleos.

## Cómo subirlo (una sola vez, ~10 minutos)

1. Creá una cuenta en https://github.com si no tenés.
2. Arriba a la derecha, **+ → New repository**. Nombre: `radar-empleos`. Dejalo **Public**: así el radar de Claude puede leer los resultados sin contraseña. Solo contiene avisos de empleo y esta configuración, nada personal. Tocá **Create repository**.
3. En la página del repo vacío, tocá **uploading an existing file**. Arrastrá **todo el contenido** de la carpeta descomprimida (incluida la carpeta `.github`) y tocá **Commit changes**.
   - Si tu sistema oculta la carpeta `.github`, creala a mano: **Add file → Create new file**, nombre `.github/workflows/radar.yml`, y pegá el contenido de ese archivo.
4. Andá a **Settings → Actions → General → Workflow permissions**, elegí **Read and write permissions** y guardá.
5. Andá a la pestaña **Actions**, elegí **Radar de Empleos** y tocá **Run workflow** para la primera corrida (tarda 2–5 minutos).
6. Cuando termine, abrí `data/report.md` en el repo para ver los resultados.

Pasale a Claude el link del repo, por ejemplo `https://github.com/TU-USUARIO/radar-empleos`, para conectar el radar.

## Cómo ajustarlo

Todo se cambia en `config.toml`, sin tocar código:

- **Sumar una empresa:** agregá su "slug" en la lista de su sistema. El slug sale de la URL de empleos de la empresa:
  - `job-boards.greenhouse.io/stripe` → greenhouse `stripe`
  - `jobs.ashbyhq.com/openai` → ashby `openai`
  - `jobs.lever.co/dlocal` → lever `dlocal`
- **Workday:** copiá un bloque `[[sources.workday]]` y completá host, tenant y site a partir de la URL `https://<host>/<site>/job/...`.
- **Slugs mal escritos:** aparecen como error en `sources_report.json`. Corregilos o borralos.
- **Exigencia del filtro:** `min_score` (más alto = más estricto) y `max_age_days`.

## Correr los tests en tu compu (opcional)

```
python -m unittest discover -s tests -t . -v
python -m radar.main
```

Necesita Python 3.11 o más nuevo. No usa librerías externas.
