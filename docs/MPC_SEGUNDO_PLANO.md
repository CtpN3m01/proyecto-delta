# MPC en segundo plano e historial por usuario

## Problema

Antes, el navegador era el cliente ExternalIO del MPC: enviaba cada bloque de
píxeles y recibía el resultado. Si el usuario cerraba la pestaña, el MPC se
detenía. Además, la cola obligaba a esperar turno incluso para la detección.

## Flujo nuevo

```text
Navegador (el usuario espera solo esta parte)
  1. Detecta rostros/placas con los modelos ONNX locales.
  2. Por cada cuadro gris x: s1, s2 = AES-CTR(k1|k2, cuadro); s0 = x - s1 - s2 (mod 256)
     ├─ party 0  <- s0 + máscara pública (gzip)       POST /api/v1/uploads/{id}/frames/{n}
     ├─ party 1  <- k1 (16 bytes, una sola vez)       POST /api/v1/uploads/{id}/key
     └─ party 2  <- k2 (16 bytes, una sola vez)
  3. POST /api/v1/browser-jobs/{id}/uploaded  -> QUEUED. Ya puede cerrar la pestaña.

Servidor (coordinator, un video a la vez, FIFO)
  4. Parties: prepare (programa delta_video_offline) -> start -> feed
     Cada Node Agent es el cliente ExternalIO C<party> y aporta SU share.
  5. result-storage es el cliente C3: recibe z = (s0+s1+s2)·(1-máscara),
     toma z mod 256, codifica H.264 con ffmpeg y publica en el catálogo.
  6. Se borran los shares de las parties; el video queda COMPLETED.
```

Ninguna entidad del servidor ve un píxel original: cada party tiene un share
uniforme y el receptor solo ve el video ya anonimizado (z = 0 en las regiones
ocultas). El cálculo es lineal con máscara pública, por eso basta con shares
módulo 256 dentro del anillo Z(2^64) de MP-SPDZ.

## Estados (historial)

| Estado | Significado | Texto en la UI |
|---|---|---|
| `UPLOADING` | el navegador detecta y entrega shares (requiere la pestaña) | Detectando en el navegador |
| `QUEUED` | shares completos, esperando turno | En cola · posición N |
| `PROCESSING` | MP-SPDZ procesa el video | Anonimizando con MPC |
| `COMPLETED` | publicado en el catálogo | Anonimizado |
| `FAILED` / `CANCELLED` | error, o pestaña cerrada antes del paso 3 | Falló / Cancelado |

El historial (`/#/historial`) muestra solo el nombre original del archivo y el
estado. Cada usuario ve únicamente sus videos: el coordinator valida el token
de PocketBase (`auth-refresh`) y guarda la cola en SQLite
(`data/coordinator/jobs.sqlite3`). Si el coordinator se reinicia, un video en
`PROCESSING` vuelve al frente de la cola: sus shares siguen en disco.

## Notas operativas

* Certificados: `cert-init` ahora genera C0–C3. Si `.runtime/` es anterior a
  este cambio se regenera automáticamente al levantar el stack.
* Disco: la party 0 guarda ~1 byte por píxel mientras el video espera
  (≈1,8 GB para 856 cuadros 1080p); las parties 1 y 2, 16 bytes.
* Rendimiento medido (3 parties + 4 clientes en un solo contenedor):
  ~1 cuadro 1080p por segundo en el servidor.
* Los endpoints de carga de las parties no tienen autenticación propia: se
  protegen con el UUID del job, igual que el transporte anterior.
