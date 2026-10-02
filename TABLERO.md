# La aplicación web

Todo el sistema se maneja desde una sola página, publicada con GitHub Pages:

**https://diegopons.github.io/balance-hidrico-lote20/**

Tiene tres pestañas.

---

## Estado

El resultado del último día calculado.

- **Condición** (Óptimo / Adecuado / Déficit / Crítico) y el porcentaje de
  agua útil.
- **Perfil del suelo**: un corte hasta 2 metros con la línea de profundidad
  de raíz y una franja que representa qué proporción de la capacidad está
  ocupada por agua disponible. Se llena de izquierda a derecha a propósito:
  un llenado desde abajo sugeriría una napa, y el agua útil está distribuida
  en toda la zona de raíces.
- **La campaña hasta hoy**: el % de agua útil a lo largo del ciclo, con la
  banda que marca la zona por debajo del umbral y las lluvias colgando desde
  arriba.
- **Vigor del cultivo**: la curva de NDVI.
- **Últimos catorce días** en tabla.

Si corresponde regar, aparece la lámina sugerida.

## Lote

El polígono que define el área de cálculo.

- Mapa satelital donde podés **dibujar** el lote o **subir un archivo**
  (GeoJSON, KML o un ZIP con el shapefile completo).
- Medidas: superficie, perímetro, vértices y centro. Conviene verificar que
  la superficie sea la que esperás antes de guardar.
- **Evolución del NDVI**: un mosaico con una imagen por fecha con pasada
  satelital útil, de la más antigua a la más reciente. Sirve para ver si un
  valor raro en la curva fue una nube sobre parte del lote o algo real en
  todo el cultivo. Las zonas grises son nube o sombra detectada.

El mosaico se genera en cada corrida y se guarda en `docs/ndvi_mosaico.png`.
Se puede desactivar en `config.yaml` (`mapas.habilitado: false`) si no se
quiere; ahorra unos segundos por corrida.

## Parámetros y ejecución

Donde se carga todo y se dispara el cálculo.

| Campo | Qué hace |
|---|---|
| Fecha de siembra | Desde cuándo calcular |
| Agua útil inicial | Lámina disponible estimada a la siembra |
| Profundidad de raíz inicial | En centímetros |
| Calcular hasta | Fecha de fin. Vacío = hasta donde haya datos |
| Umbral de riego | % de agua útil que dispara la alerta |
| Nombre del lote | Aparece en el aviso de Telegram |
| Cuándo avisar | Modo de notificación (ver TELEGRAM.md) |

Los campos vacíos usan lo que diga `config.yaml`, así que las corridas
automáticas de las 6 AM siguen funcionando sin tocar nada.

Y tres casillas:

- **Calcular hasta hoy**: pide hasta la fecha de ejecución. Los días que
  AgERA5 todavía no publicó quedan fuera y entran en la corrida siguiente.
- **Enviar el resumen por Telegram**: fuerza el aviso aunque no haya días
  nuevos y aunque el modo no corresponda.
- **Reiniciar el balance desde cero**: descarta lo acumulado y recalcula.

---

## El botón de guardar y ejecutar

Escribe el lote en el repositorio y lanza una corrida, todo de una.

Necesita un **token de GitHub** *fine-grained*, limitado a este repositorio,
con permisos **Contents** y **Actions** en lectura y escritura. Se crea en:
GitHub → Settings (de la cuenta) → Developer settings → Personal access
tokens → Fine-grained tokens.

El token se usa solo desde el navegador: no viaja a ningún otro lado ni
queda en el repositorio. Con la casilla "recordarlo" queda guardado en ese
navegador; sin ella, se olvida al cerrar la pestaña.

> El token da acceso de escritura a este repositorio. Está bien en tu propia
> máquina, pero no lo dejes guardado en una compartida, y si alguna vez se
> expone, revocalo desde GitHub: se hace en diez segundos.

---

## Cuándo se reinicia solo el balance

El sistema guarda una huella del lote y de la fecha de siembra. Si cualquiera
de los dos cambia, el balance acumulado ya no corresponde: se reinicia desde
cero automáticamente.

En ese caso **la serie anterior no se pierde**: se renombra a
`balance_hidrico_lote20_hasta_AAAAMMDD-HHMMSS.csv` dentro de `data/`, y la
nueva arranca limpia. Antes de este cambio las dos series se mezclaban en el
mismo archivo y el gráfico mostraba una curva continua que nunca existió.

---

## Verlo sin publicarlo

Descargá el repositorio (botón verde **Code** → **Download ZIP**),
descomprimilo, entrá a `docs` y abrí `index.html`.

Si aparece vacío al abrirlo con doble clic, es una restricción del navegador
con archivos locales: abrí una consola en `docs`, ejecutá
`python -m http.server`, y entrá a `http://localhost:8000`.

---

## Qué queda expuesto

El repositorio es público, que es lo que permite publicar la página sin
costo. Eso significa:

**No queda expuesto**: las claves de Copernicus ni el token de Telegram.
Viven en los Secrets de GitHub, cifrados.

**Sí queda visible**: la ubicación del lote, la serie de datos y los
registros de cada corrida.

**La página no tiene contraseña**: quien tenga el enlace, entra.

---

## Parámetros duplicados

El tablero tiene su propia copia de tres valores, al principio del bloque
`<script>` de `docs/index.html`:

```javascript
const UMBRAL_RIEGO = 50;   // % de agua útil que dispara la alerta
const EFICIENCIA = 0.85;   // eficiencia de aplicación del riego
const PROF_MAX = 200;      // profundidad del perfil, en cm
```

Si los cambiás en `config.yaml` (que es lo que usan el cálculo y las alertas),
acordate de cambiarlos también acá, o el tablero va a mostrar un criterio
distinto del que aplica el sistema. Es la única duplicación que quedó.
