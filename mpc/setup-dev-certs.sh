#!/usr/bin/env bash
set -euo pipefail

runtime_root="${1:-/runtime}"
runtime_uid="${RUNTIME_UID:?RUNTIME_UID must be set}"
runtime_gid="${RUNTIME_GID:?RUNTIME_GID must be set}"
cert_dir="${runtime_root}/Player-Data"

if [[ "${EUID}" -ne 0 ]]; then
    echo "setup-dev-certs.sh must run as root to fix bind-mount ownership" >&2
    exit 1
fi

if [[ ! "${runtime_uid}" =~ ^[0-9]+$ || ! "${runtime_gid}" =~ ^[0-9]+$ ]]; then
    echo "RUNTIME_UID and RUNTIME_GID must be numeric" >&2
    exit 1
fi

mkdir -p "${cert_dir}"

# Clientes ExternalIO: C0 (navegador/CLI y aporte de la party 0), C1 y C2
# (aporte de las parties 1 y 2) y C3 (result-storage recibe el resultado).
complete=1
for file in P0.pem P0.key P1.pem P1.key P2.pem P2.key C0.pem C0.key C1.pem C1.key C2.pem C2.key C3.pem C3.key; do
    if [[ ! -s "${cert_dir}/${file}" ]]; then
        complete=0
    fi
done

for file in P0.pem P1.pem P2.pem C0.pem C1.pem C2.pem C3.pem; do
    # Reutilizar solo certificados legibles con al menos un día de vigencia.
    if ! openssl x509 -in "${cert_dir}/${file}" -checkend 86400 -noout >/dev/null 2>&1; then
        complete=0
    fi
done

if [[ "${complete}" -eq 0 ]]; then
    # setup-ssl.sh elimina *.0 sin -f; el placeholder hace seguro el primer uso.
    touch "${cert_dir}/bootstrap.0"
    /opt/MP-SPDZ/Scripts/setup-ssl.sh 3 "${cert_dir}"
    (
        cd "${runtime_root}"
        /opt/MP-SPDZ/Scripts/setup-clients.sh 4
    )
fi

c_rehash "${cert_dir}"
# Each deployed party sees its own private key, the transport-client key,
# and public peer certificates. It cannot read other parties' private keys.
for party in 0 1 2; do
    isolated="${runtime_root}/party-${party}/Player-Data"
    mkdir -p "${isolated}"
    cp "${cert_dir}"/*.pem "${isolated}/"
    # C0 conserva el transporte del navegador/CLI; C<party> es el aporte offline.
    cp "${cert_dir}/P${party}.key" "${cert_dir}/C0.key" "${isolated}/"
    if [[ "${party}" -ne 0 ]]; then
        cp "${cert_dir}/C${party}.key" "${isolated}/"
    fi
    c_rehash "${isolated}"
    mkdir -p "${runtime_root}/logs/party-${party}"
done
# result-storage solo tiene la clave del cliente de salida y certificados públicos.
collector="${runtime_root}/collector/Player-Data"
mkdir -p "${collector}"
cp "${cert_dir}"/*.pem "${cert_dir}/C3.key" "${collector}/"
c_rehash "${collector}"
touch "${runtime_root}/certificates.ready"

chown "${runtime_uid}:${runtime_gid}" "${runtime_root}" "${runtime_root}/certificates.ready"
for party in 0 1 2; do
    chown -R "${runtime_uid}:${runtime_gid}" \
        "${cert_dir}" \
        "${runtime_root}/party-${party}" \
        "${runtime_root}/logs/party-${party}"
done
chown -R "${runtime_uid}:${runtime_gid}" "${runtime_root}/collector"
