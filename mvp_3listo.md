# MVP 3 listo — cómo encenderlo y usarlo, paso a paso

Esta guía es para **Windows con PowerShell** y esta carpeta:

```text
C:\Proyectos\ProyectoDelta\proyecto-delta
```

Sigue los pasos en orden. Copia solo lo que aparece dentro de cada bloque de
comandos y pulsa **Enter**. Si una ruta es diferente en tu computadora, cámbiala.

## 1. Abrir Docker Desktop

1. Abre el menú Inicio de Windows.
2. Busca **Docker Desktop** y ábrelo.
3. Espera hasta que indique que el motor está funcionando, por ejemplo
   **Engine running**.
4. Déjalo abierto mientras uses el proyecto.

Si Docker pide iniciar sesión, actualizarse o reiniciar Windows, termina ese paso
antes de continuar.

## 2. Abrir una terminal PowerShell

En Visual Studio Code, abre **Terminal → Nueva terminal** y elige **PowerShell**.
También puedes abrir PowerShell desde el menú Inicio de Windows.

Copia este comando y pulsa Enter:

```powershell
Set-Location 'C:\Proyectos\ProyectoDelta\proyecto-delta'
```

Para comprobar que estás en la carpeta correcta:

```powershell
Test-Path .\docker-compose.yml
```

Debe aparecer `True`. Si aparece `False`, revisa la ruta del primer comando.

## 3. Encender todo

**En este equipo las imágenes ya están construidas.** El arranque habitual es:

```powershell
$env:HOST_UID = '0'
$env:HOST_GID = '0'
docker compose up -d --no-build --wait
```

Copia las tres líneas juntas. Espera hasta que termine y puedas volver a escribir
en la terminal. No cierres Docker Desktop.

Este comando enciende las dos webs, PocketBase, el almacenamiento, Coordinator y
las tres parties MPC. También prepara los certificados necesarios.

No necesitas ejecutar Python ni `npm run dev` para usar las webs de Docker.
Tampoco necesitas copiar archivos `.env` para el funcionamiento local normal.

Los valores `HOST_UID` y `HOST_GID` se usan así en **Windows con Docker Desktop**.
Debes volver a escribir esas dos líneas si abres otra terminal para arrancar el
proyecto. En Linux se utilizan el UID y GID reales del operador.

### Si dice que falta una imagen, o estás preparando otra computadora

Primero comprueba que tengas estas dos carpetas:

```text
C:\Proyectos\ProyectoDelta\
├── proyecto-delta\
└── MP-SPDZ\
```

`MP-SPDZ` debe ser el clon compatible que utiliza este proyecto. Se necesita para
construir las imágenes MPC desde el código fuente; no hace falta recompilarlo
para el arranque habitual con imágenes existentes.

Desde `proyecto-delta`, ejecuta:

```powershell
$env:HOST_UID = '0'
$env:HOST_GID = '0'
docker compose up --build -d --wait
```

La primera construcción necesita Internet y puede tardar bastante, especialmente
MP-SPDZ. Déjala terminar. Este es también el arranque para reconstruir las imágenes
después de cambiar código que va dentro de Docker.

En los siguientes arranques puedes volver al comando con `--no-build`.

## 4. Comprobar que encendió

Ejecuta:

```powershell
docker compose ps
```

Debes ver estos servicios en ejecución, con estado `Up` o `running`:

- `pocketbase`
- `coordinator-api`
- `party-0`
- `party-1`
- `party-2`
- `result-storage`
- `processing-web`
- `catalog-web`

PocketBase, Coordinator y las parties también deben indicar `healthy`.
Las webs y el almacenamiento no necesitan mostrar esa palabra para estar activos.

`cert-init` es una tarea que prepara certificados y termina. Que aparezca como
`Exited (0)` al consultar `docker compose ps -a` es normal.

Ahora abre estas direcciones en el navegador:

| Qué quieres abrir | Dirección |
| --- | --- |
| Web para iniciar sesión y procesar videos | http://localhost:8080 |
| Web para descargar videos anonimizados | http://localhost:8081 |
| Panel para administrar PocketBase | http://127.0.0.1:8090/_/ |

Escribe la dirección completa en la barra del navegador. Se recomienda Chrome;
la integración también se verificó con Edge Chromium. No necesitas tener una
terminal de Vite abierta para estas direcciones.

## 5. Preparar las cuentas: solo la primera vez

**No hay usuarios ni contraseñas demo.** Si ya tienes una cuenta de la aplicación
que funciona, salta al paso 6.

Vas a crear dos cuentas con funciones distintas:

| Cuenta | Para qué sirve |
| --- | --- |
| Superusuario de PocketBase | Entrar en el panel de la base de datos, en el puerto 8090. |
| Usuario de la aplicación con rol `admin` | Entrar en la web del puerto 8080 y crear otras cuentas. |

### 5.1. Crear el superusuario de PocketBase

Con Docker y los servicios encendidos, vuelve a la terminal del paso 2 y copia
este bloque:

```powershell
& {
    $correoPB = Read-Host 'Escribe el correo para administrar PocketBase'
    $clavePB = Read-Host 'Escribe una contraseña larga y propia' -AsSecureString
    $credencialPB = [System.Net.NetworkCredential]::new($correoPB, $clavePB)
    docker compose exec pocketbase /pb/pocketbase superuser upsert $correoPB $credencialPB.Password
    Remove-Variable clavePB, credencialPB
}
```

El bloque te pedirá el correo y la contraseña. Escribe cada uno y pulsa Enter.
Los caracteres de la contraseña se ocultan: es normal. Anota tus credenciales
en un lugar privado; las necesitarás enseguida.

Este paso es para la instalación inicial. Si utilizas un correo de superusuario
que ya existe, `upsert` cambia su contraseña. Si ya puedes entrar al panel, no
necesitas repetirlo.

### 5.2. Entrar en el panel de PocketBase

1. Abre http://127.0.0.1:8090/_/.
2. Inicia sesión con el correo y la contraseña del paso 5.1.
3. Busca **Collections** en el panel.
4. Abre la colección llamada **users**.

Si ves un instalador en lugar del formulario de acceso, puedes completar allí la
creación del primer superusuario. El comando anterior permite preparar esa cuenta
sin depender de un enlace temporal de instalación.

### 5.3. Crear tu administrador de la aplicación

Dentro de la colección **users**:

1. Pulsa **New record** o **Nuevo registro**.
2. Escribe el correo de tu cuenta de la aplicación en **email**.
3. Escribe una contraseña propia en **password** y repítela si aparece un campo
   de confirmación.
4. Escribe tu nombre en **name**. Debe tener entre 2 y 80 caracteres.
5. Selecciona **admin** en **role**.
6. Guarda el registro con **Create**, **Save** o el botón equivalente del panel.

Ya tienes la cuenta que utilizarás en la web de procesamiento. Para este acceso
se usa un registro de **users**, no la cuenta de superusuario de PocketBase.

## 6. Entrar en la aplicación y crear más usuarios

1. Abre http://localhost:8080.
2. Escribe el correo y la contraseña de la cuenta creada en el paso 5.3.
3. Pulsa **Iniciar sesión**.
4. Para dar acceso a otra persona, entra en **Usuarios**.
5. Pulsa **Crear usuario** y completa nombre, correo y contraseña.
6. Elige el rol:
   - **Usuario**: permite entrar y procesar videos.
   - **Administrador**: además permite crear cuentas y consultar usuarios.
7. Guarda la cuenta y comparte sus credenciales de forma privada con esa persona.

El correo no se puede repetir entre cuentas. Un usuario normal no verá la sección
**Usuarios**. No existe registro público.

Las cuentas se conservan al apagar y volver a encender el proyecto. Crear la
primera cuenta no es un paso que debas repetir todos los días.

## 7. Procesar un video

1. Entra en http://localhost:8080 con una cuenta de la aplicación.
2. Pulsa **Seleccionar video**.
3. Elige un archivo MP4 de tu computadora. Para una primera prueba puedes usar
   `C:\Proyectos\ProyectoDelta\video3.mp4`, si todavía está en esa ubicación.
4. La selección inicia el procesamiento automáticamente.
5. Mantén la pestaña abierta y espera. Aunque el video sea corto, puede tardar
   varios minutos. La pantalla muestra el progreso por cuadros y, si hay otro
   trabajo activo, la posición en la cola.
6. Espera el mensaje **Video anonimizado y almacenado correctamente**.

La vista previa muestra tu original local. La descarga del resultado se realiza
en la otra web. La salida anonimizada se guarda automáticamente, en gris y sin
audio. Los conteos son estimaciones de los modelos.

## 8. Descargar el resultado

1. Abre otra pestaña con http://localhost:8081.
2. Pulsa **Actualizar listado**.
3. Busca el resultado por su fecha y hora.
4. Pulsa **Descargar video anonimizado**.
5. El navegador descargará el MP4 a tu carpeta de descargas, o te preguntará dónde
   guardarlo según su configuración.

Esta segunda web no pide iniciar sesión. Solo aparecen los resultados publicados
después de completar el procesamiento y el guardado.

## 9. Apagar todo al terminar

Si un video sigue procesándose, espera a que termine o cancélalo desde la web.
Después, abre PowerShell y ejecuta:

```powershell
Set-Location 'C:\Proyectos\ProyectoDelta\proyecto-delta'
docker compose down
```

Este comando apaga los servicios del proyecto y conserva los usuarios y videos
guardados. No agregues `-v`: esa opción elimina los volúmenes con esos datos.

Para comprobar que quedó apagado:

```powershell
docker compose ps
```

La lista debe quedar vacía; puede aparecer solamente la cabecera de la tabla.
Si también habías abierto `npm run dev`, ve a esa terminal y pulsa **Ctrl+C**.
Después puedes cerrar Docker Desktop si ya no lo necesitas para otros proyectos.

## 10. Volver a encenderlo otro día

Abre Docker Desktop, espera a que esté listo y ejecuta en PowerShell:

```powershell
Set-Location 'C:\Proyectos\ProyectoDelta\proyecto-delta'
$env:HOST_UID = '0'
$env:HOST_GID = '0'
docker compose up -d --no-build --wait
```

Luego abre http://localhost:8080 y usa tu cuenta existente. El catálogo sigue en
http://localhost:8081. No necesitas crear las cuentas otra vez.

## Opcional: trabajar en el código de las webs con Vite

Para usar la aplicación normalmente, basta el arranque Docker anterior. Esta
opción sirve cuando quieres editar el frontend y ver los cambios al guardar.
Requiere Node.js 22.12 o posterior y los servicios Docker del paso 3 activos.

Abre otra terminal PowerShell y ejecuta:

```powershell
Set-Location 'C:\Proyectos\ProyectoDelta\proyecto-delta\frontend'
npm.cmd ci
npm.cmd run dev
```

`npm.cmd ci` instala las dependencias: úsalo la primera vez o cuando cambie el
archivo `package-lock.json`. Para arranques posteriores basta `npm.cmd run dev`.

Un solo servidor sirve las dos webs:

- Procesamiento: http://127.0.0.1:5173
- Descargas: http://127.0.0.1:5173/catalog.html

Mantén esa terminal abierta. Para detenerlo, pulsa **Ctrl+C**. Esto detiene Vite;
los servicios Docker se apagan aparte con `docker compose down` desde la raíz.

## Si algo falla

### Dice que Docker no está funcionando o que no puede conectar con el daemon

Abre Docker Desktop, espera a **Engine running** y repite el paso 3.

### Dice que no encuentra el archivo de configuración

Vuelve al paso 2. Ejecuta los comandos `docker compose` desde la carpeta que
contiene `docker-compose.yml`, no desde `frontend`.

### Dice que un puerto ya está ocupado

Revisa si tienes otro proyecto o servidor utilizando ese puerto. No cierres
procesos de Windows al azar. Los puertos de este proyecto son 8080, 8081, 8090,
8000, 8100–8102, 8200 y 14000–14002. Vite utiliza 5173.

### La página no abre

Revisa el paso 4 y asegúrate de usar `http://`, la dirección y el puerto indicados.
Las webs Docker usan 8080 y 8081. El puerto 5173 solo funciona si encendiste Vite.

### El correo o la contraseña no funcionan

Comprueba que la cuenta exista en **Collections → users**, con nombre y rol
`admin` o `user`. Usa la contraseña de esa cuenta en la web 8080. Las credenciales
del superusuario sirven para el panel 8090. Las cuentas demo antiguas ya no existen.

### Un servicio no arranca o el procesamiento muestra un error

Desde la raíz, consulta el estado y los últimos mensajes:

```powershell
docker compose ps -a
docker compose logs --tail=40 coordinator-api party-0 party-1 party-2 result-storage
```

Para problemas de acceso o creación de cuentas:

```powershell
docker compose logs --tail=40 pocketbase
```

Si los logs muestran un enlace de instalación de PocketBase, contiene acceso
temporal al instalador: no lo publiques ni lo compartas como una captura pública.

Esta guía es para uso local. El detalle técnico y las limitaciones del MVP están
en [docs/EJECUCION_MVP.md](docs/EJECUCION_MVP.md) y [docs/T49.md](docs/T49.md).
