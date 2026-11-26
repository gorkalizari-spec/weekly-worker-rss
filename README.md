# Weekly Worker en RSS

Canales independientes para leer los artículos de *Weekly Worker* en inglés. Copia la dirección de un canal en la opción **Añadir fuente** de tu lector. Los enlaces de cada noticia abren la publicación original.

| Canal | Suscripción |
| --- | --- |
| **Todas las publicaciones** | [RSS general](https://raw.githubusercontent.com/gorkalizari-spec/weekly-worker-rss/main/feeds/general.xml) |
| Party & Programme | [RSS](https://raw.githubusercontent.com/gorkalizari-spec/weekly-worker-rss/main/feeds/party-programme.xml) |
| Democracy & State | [RSS](https://raw.githubusercontent.com/gorkalizari-spec/weekly-worker-rss/main/feeds/democracy-state.xml) |
| Imperialism & War | [RSS](https://raw.githubusercontent.com/gorkalizari-spec/weekly-worker-rss/main/feeds/imperialism-war.xml) |
| Capitalism & Crisis | [RSS](https://raw.githubusercontent.com/gorkalizari-spec/weekly-worker-rss/main/feeds/capitalism-crisis.xml) |
| Society & Culture | [RSS](https://raw.githubusercontent.com/gorkalizari-spec/weekly-worker-rss/main/feeds/society-culture.xml) |
| CPGB News | [RSS](https://raw.githubusercontent.com/gorkalizari-spec/weekly-worker-rss/main/feeds/cpgb-news.xml) |

## Cobertura

El periódico publica un RSS oficial. El 26 de noviembre de 2026 contenía diez entradas del número 1611, sin fecha individual, autor ni categoría. El sumario enlazaba once publicaciones, incluida la página de cartas. El servicio consulta ambas fuentes y completa los datos desde las páginas originales. [RSS del periódico](https://weeklyworker.co.uk/worker/rss/) · [Sumario del 1611](https://weeklyworker.co.uk/worker/1611/) · [Archivo por años](https://weeklyworker.co.uk/worker/)

El general reúne todos los artículos HTML recuperados, incluidas cartas, anuncios y publicaciones sin sección. Cada página de cartas tiene una dirección por número y conserva las firmas identificables. Una publicación puede pertenecer a varios canales. Cuando falta la entradilla, se toma un extracto de hasta 280 caracteres del primer párrafo disponible, marcado como «Excerpt» en el lector. Los nombres de autor proceden de la ficha o de las firmas de las cartas. Una autoría ausente queda vacía. La fecha corresponde al día editorial, representado a medianoche UTC para su uso en RSS. El canal contiene metadatos y remite al texto completo del periódico. [Equipo web y condiciones de reutilización](https://www.weeklyworker.co.uk/worker/1011/from-the-web-team/)

Cada seis horas se comprueban las novedades; además, cada ejecución procesa hasta dos números pendientes del archivo. El canal crece durante la recuperación histórica. El recuento de artículos, los números completados, los pendientes descubiertos y los índices anuales ya consultados figuran en el informe. Un número que solo ofrece PDF cuenta como revisado y aporta cero fichas HTML. [Cobertura actual](state/coverage.json)

## Actualización y mantenimiento

GitHub Actions se inicia en la rama `main` a las 00:23, 06:23, 12:23 y 18:23 UTC. GitHub puede retrasar el inicio. Para comprobar una ejecución o repetirla, abre **Actions → Actualizar RSS → Run workflow**. No se necesitan contraseñas del periódico ni claves externas. [Historial de ejecuciones](https://github.com/gorkalizari-spec/weekly-worker-rss/actions/workflows/update.yml)

El proceso consulta las reglas de acceso, usa una sola conexión a la vez, espacia las peticiones al menos dos segundos y acepta pausas más largas indicadas por el servidor. Aprovecha ETag y Last-Modified cuando existen. Conserva el catálogo entre ejecuciones y compara los sumarios para detectar novedades sin descargar otra vez todas las fichas. Revisa los números recientes y vuelve a comprobar los antiguos por turnos. La dirección original es el identificador permanente de cada entrada.

Si una página enlazada da 404 o cambia de formato, queda pendiente para un nuevo intento y la ejecución muestra una advertencia. Un bloqueo de acceso o un error de red conserva los canales ya publicados. El estado y los canales se publican en un único commit. Los números que se digitalicen posteriormente se descubren al volver a recorrer los índices anuales.

### Ejecución local opcional

Se necesita Python 3.12. Ejecuta estos comandos desde la carpeta del proyecto.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests
python update.py
```

Los canales se escriben en `feeds/` y el catálogo en `state/`. Para verificar novedades sin adelantar la carga histórica, usa `python update.py --backfill 0`.
