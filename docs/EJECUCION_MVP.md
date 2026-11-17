# Ejecución del MVP web de Proyecto Delta

Esta guía inicia PocketBase, prepara las cuentas de acceso y ejecuta el frontend. Incluye el arranque completo de los servicios MPC y una opción ligera para trabajar solo en autenticación. Los comandos están escritos para ejecutarse desde la raíz del repositorio, salvo cuando se indique `frontend/`.

## Qué se implementó

- Se añadió PocketBase `0.42.3` como servicio de Docker Compose, ligado a `127.0.0.1:8090`, con datos persistentes en `pocketbase-data`.
- Una migración configura la colección de autenticación `users` con `name` y `role`; sus reglas permiten listar y administrar cuentas solo a roles `admin`.
- El frontend usa el SDK oficial de PocketBase para autenticar, recuperar la sesión en la pestaña y crear/listar usuarios desde el panel de administración. No usa cuentas precargadas ni permite registro público.
- El superusuario de PocketBase se usa para instalar y administrar PocketBase. La aplicación requiere una cuenta aparte en `users` con rol `admin`; esa cuenta puede crear usuarios `user` y otros administradores.

## Requisitos

- Docker Engine o Docker Desktop con Docker Compose.
- Para levantar el procesamiento MPC completo, el clon de MP-SPDZ como carpeta hermana de `proyecto-delta`:

  ```text
  ProyectoDelta/
  ├── proyecto-delta/
  └── MP-SPDZ/
  ```

- Node.js 22.12 o posterior y npm para el frontend.

PocketBase se compila desde `docker/pocketbase.Dockerfile`, fija PocketBase `0.42.3` y almacena los datos en el volumen Docker `pocketbase-data`. La migración de `pb_migrations/` configura los campos `name` y `role` de `users` y restringe el acceso administrativo con reglas del servidor.

## 1. Levantar los servicios

### MVP completo con procesamiento MPC

En Linux/macOS, desde la raíz del repositorio:

```bash
cd /home/benji/TEC/proyecto-delta
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"
docker compose up --build -d
docker compose ps
```

La primera construcción de las parties MPC puede tardar varios minutos. Espera a que `coordinator-api`, `client-api` y `party-0`/`party-1`/`party-2` estén saludables. `cert-init` debe aparecer como completado.

En Windows PowerShell, reemplaza la ruta de ejemplo por la ubicación de tu checkout:

```powershell
Set-Location 'C:\ruta\proyecto-delta'
docker compose up --build -d
docker compose ps
```

Si solo estás integrando el login y no necesitas procesar videos todavía, puedes iniciar únicamente PocketBase:

```bash
docker compose up --build -d pocketbase
docker compose ps pocketbase
```

El servicio escucha en `127.0.0.1:8090`. La API debe responder en `http://127.0.0.1:8090/api/health`.

## 2. Crear el superusuario de PocketBase

Desde la raíz del repositorio, crea el superusuario con una dirección de correo y contraseña propias:

```bash
docker compose exec pocketbase /pb/pocketbase superuser upsert 'tu-correo@ejemplo.com' 'UnaClaveSegura123'
```

En PowerShell se utiliza el mismo comando. `upsert` crea el superusuario si no existe; si el correo ya existe, actualiza su contraseña. No compartas esa contraseña.

Ahora abre [http://127.0.0.1:8090/_/](http://127.0.0.1:8090/_/) e inicia sesión con el superusuario. Si usas el enlace temporal que aparece en `docker compose logs pocketbase`, reemplaza `0.0.0.0` por `127.0.0.1` antes de abrirlo.

### Crear la primera cuenta de la aplicación

El superusuario de PocketBase administra la base y el Dashboard; **no es la cuenta que inicia sesión en el frontend**. En el Dashboard:

1. Abre **Collections → users**. La migración crea esta colección al iniciar PocketBase.
2. Crea un registro con correo, contraseña, nombre y rol `admin`.
3. Guarda la cuenta. Usa sus credenciales en el login de TecPeopleFlow.

Desde entonces, los administradores de la aplicación pueden crear cuentas con rol `user` o `admin` desde la sección **Usuarios** del frontend. No hay registro público.

## 3. Configurar y ejecutar el frontend

En una terminal nueva:

```bash
cd /home/benji/TEC/proyecto-delta/frontend
cp .env.example .env
npm install
npm run dev
```

Vite muestra la dirección local; por defecto es [http://127.0.0.1:5173](http://127.0.0.1:5173). Abre la aplicación, inicia sesión con la cuenta de aplicación `admin` y entra a **Usuarios** para dar de alta más cuentas.

`frontend/.env` define `VITE_POCKETBASE_URL`. Para el entorno local predeterminado debe ser:

```dotenv
VITE_POCKETBASE_URL=http://127.0.0.1:8090
```

PowerShell equivalente para preparar el frontend:

```powershell
Set-Location 'C:\ruta\proyecto-delta\frontend'
Copy-Item .env.example .env
npm.cmd install
npm.cmd run dev
```

Si ya existe un archivo `.env`, no lo sobrescribas con `Copy-Item`; verifica que incluya `VITE_POCKETBASE_URL`.

## Servicios y puertos locales

| Servicio | Dirección local | Uso |
| --- | --- | --- |
| PocketBase | `127.0.0.1:8090` | Dashboard, autenticación y usuarios |
| Coordinator | `localhost:8000` | Control de trabajos MPC |
| Client API | `127.0.0.1:8001` | Recibe el video y ejecuta el cliente confiable |
| Node Agents | `localhost:8100`–`8102` | Control de las tres parties |
| Vite | `127.0.0.1:5173` | Frontend web |

## Comandos útiles

Desde la raíz del proyecto:

```bash
# Ver estado de los servicios
docker compose ps

# Ver logs de PocketBase
docker compose logs --tail=100 pocketbase

# Seguir todos los logs
docker compose logs -f

# Reconstruir y aplicar cambios de servicios o migraciones
docker compose up --build -d

# Detener servicios; conserva la base de PocketBase
docker compose down
```

Para validar frontend y pruebas unitarias:

```bash
cd frontend
npm test
npm run build
```

Las pruebas E2E autenticadas requieren una cuenta `admin` y una cuenta `user` ya creadas en PocketBase. En bash, configura sus credenciales antes de correrlas:

```bash
export E2E_ADMIN_EMAIL='admin@ejemplo.com'
export E2E_ADMIN_PASSWORD='contraseña-del-admin'
export E2E_USER_EMAIL='usuario@ejemplo.com'
export E2E_USER_PASSWORD='contraseña-del-usuario'
npm run test:e2e
```

## Si no puedes crear el superusuario

Comprueba primero el estado y los logs:

```bash
docker compose ps pocketbase
docker compose logs --tail=100 pocketbase
```

Si el contenedor está saludable pero el Dashboard no muestra el instalador, ejecuta el comando `superuser upsert` de la sección 2. Si el enlace temporal del log contiene `0.0.0.0`, reemplaza esa parte por `127.0.0.1`.

Los usuarios se guardan en el volumen nombrado `pocketbase-data`, por lo que `docker compose down` no los elimina.
