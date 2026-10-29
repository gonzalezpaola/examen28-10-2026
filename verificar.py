"""Califica el examen simplificado de inventario de red.

Uso:

    python verificar.py plantilla
    python verificar.py solucion

Una fase se aprueba solo si pasa todos sus criterios. El examen se
aprueba con 2 o 3 fases. El script copia la entrega a un temporal y
no modifica los archivos del estudiante.

Códigos de salida: 0 aprobado, 1 no aprobado, 2 uso incorrecto.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from pathlib import Path


CATALOGO = {
    "SSH": (22, "TCP"),
    "DNS": (53, "UDP"),
    "DHCP": (67, "UDP"),
    "HTTP": (80, "TCP"),
    "HTTPS": (443, "TCP"),
}

TIPOS = {
    "router",
    "switch",
    "servidor",
    "access-point",
    "telefono",
    "teléfono",
    "firewall",
}

LLAVES = ("campus", "vlan_admin", "vlans", "dispositivos", "protocolos")
LLAVES_VLAN = ("id", "nombre", "uso")
LLAVES_DISPOSITIVO = ("hostname", "ip", "tipo", "vlan_id")
LLAVES_PROTOCOLO = ("nombre", "puerto", "transporte", "vlan_id")


class Fase:
    def __init__(self, numero, titulo):
        self.numero = numero
        self.titulo = titulo
        self.puntos = []

    def agregar(self, ok, nombre, detalle=""):
        texto = " ".join(str(detalle).split()) if detalle else ""
        self.puntos.append((bool(ok), nombre, texto))

    @property
    def aprobada(self):
        return bool(self.puntos) and all(ok for ok, _, _ in self.puntos)

    def resumen(self):
        hechas = sum(1 for ok, _, _ in self.puntos if ok)
        estado = "APROBADA" if self.aprobada else "NO APROBADA"
        return f"Fase {self.numero}: {estado} ({hechas}/{len(self.puntos)})"


def configurar_salida():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def explicar(exc):
    return f"{type(exc).__name__}: {exc}"


def recorte(valor):
    texto = repr(valor)
    return texto if len(texto) <= 160 else texto[:160] + "..."


def leer(path):
    raw = Path(path).read_bytes()
    for codec in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def es_entero(valor):
    return isinstance(valor, int) and not isinstance(valor, bool)


def ip_valida(ip):
    if not isinstance(ip, str):
        return False
    partes = ip.split(".")
    if len(partes) != 4:
        return False
    for parte in partes:
        if not parte.isdigit():
            return False
        numero = int(parte)
        if numero > 255 or str(numero) != parte:
            return False
    return True


def marcar(fase, nombre, errores):
    if errores:
        fase.agregar(False, nombre, "; ".join(errores[:8]))
    else:
        fase.agregar(True, nombre)


def revisar_contenido(campus, vlan_admin, vlans, dispositivos, protocolos):
    secciones = {"Variables": [], "VLANs": [], "Dispositivos": [], "Protocolos": []}

    if not isinstance(campus, str) or not campus.strip():
        secciones["Variables"].append("campus debe ser texto no vacío")
    if not es_entero(vlan_admin) or not 1 <= vlan_admin <= 4094:
        secciones["Variables"].append("vlan_admin debe ser un entero entre 1 y 4094")

    ids = set()
    if not isinstance(vlans, list) or len(vlans) < 3:
        secciones["VLANs"].append("se necesitan al menos 3 VLANs")
    else:
        for indice, vlan in enumerate(vlans, start=1):
            if not isinstance(vlan, dict):
                secciones["VLANs"].append(f"la VLAN {indice} no es un diccionario")
                continue
            faltan = [llave for llave in LLAVES_VLAN if llave not in vlan]
            if faltan:
                secciones["VLANs"].append(f"la VLAN {indice} no tiene: {', '.join(faltan)}")
                continue
            if not es_entero(vlan["id"]) or not 1 <= vlan["id"] <= 4094:
                secciones["VLANs"].append(f"id fuera de rango: {vlan['id']!r}")
            elif vlan["id"] in ids:
                secciones["VLANs"].append(f"id repetido: {vlan['id']}")
            else:
                ids.add(vlan["id"])
            if not isinstance(vlan["nombre"], str) or not vlan["nombre"].strip():
                secciones["VLANs"].append(f"la VLAN {vlan['id']} no tiene nombre")
            if not isinstance(vlan["uso"], str) or not vlan["uso"].strip():
                secciones["VLANs"].append(f"la VLAN {vlan['id']} no tiene uso")
    if ids and es_entero(vlan_admin) and vlan_admin not in ids:
        secciones["Variables"].append("vlan_admin no está en la lista de VLANs")

    if not isinstance(dispositivos, list) or len(dispositivos) < 4:
        secciones["Dispositivos"].append("se necesitan al menos 4 dispositivos")
    else:
        hostnames, direcciones, tipos, en_uso = set(), set(), set(), set()
        for indice, dispositivo in enumerate(dispositivos, start=1):
            if not isinstance(dispositivo, dict):
                secciones["Dispositivos"].append(f"el dispositivo {indice} no es un diccionario")
                continue
            faltan = [llave for llave in LLAVES_DISPOSITIVO if llave not in dispositivo]
            if faltan:
                secciones["Dispositivos"].append(
                    f"el dispositivo {indice} no tiene: {', '.join(faltan)}"
                )
                continue
            hostname = dispositivo["hostname"]
            if not isinstance(hostname, str) or not hostname.strip():
                secciones["Dispositivos"].append(f"hostname vacío en la posición {indice}")
            elif hostname in hostnames:
                secciones["Dispositivos"].append(f"hostname repetido: {hostname}")
            else:
                hostnames.add(hostname)
            ip = dispositivo["ip"]
            if not ip_valida(ip):
                secciones["Dispositivos"].append(f"IP inválida en {hostname}: {ip!r}")
            elif ip in direcciones:
                secciones["Dispositivos"].append(f"IP repetida: {ip}")
            else:
                direcciones.add(ip)
            tipo = dispositivo["tipo"]
            if not isinstance(tipo, str) or tipo.lower() not in TIPOS:
                secciones["Dispositivos"].append(f"tipo no permitido en {hostname}: {tipo!r}")
            else:
                tipos.add(tipo.lower())
            vlan_id = dispositivo["vlan_id"]
            if not es_entero(vlan_id) or (ids and vlan_id not in ids):
                secciones["Dispositivos"].append(f"{hostname} apunta a una VLAN inexistente")
            else:
                en_uso.add(vlan_id)
        if "router" not in tipos or "switch" not in tipos:
            secciones["Dispositivos"].append("incluye al menos un router y un switch")
        if len(en_uso) < 2:
            secciones["Dispositivos"].append("los equipos deben ocupar al menos dos VLANs")

    if not isinstance(protocolos, list) or len(protocolos) < 3:
        secciones["Protocolos"].append("se necesitan al menos 3 protocolos del catálogo")
    else:
        transportes = set()
        hay_ssh = False
        hay_ssh_admin = False
        for indice, protocolo in enumerate(protocolos, start=1):
            if not isinstance(protocolo, dict):
                secciones["Protocolos"].append(f"el protocolo {indice} no es un diccionario")
                continue
            faltan = [llave for llave in LLAVES_PROTOCOLO if llave not in protocolo]
            if faltan:
                secciones["Protocolos"].append(
                    f"el protocolo {indice} no tiene: {', '.join(faltan)}"
                )
                continue
            nombre = str(protocolo["nombre"]).strip().upper()
            if nombre not in CATALOGO:
                secciones["Protocolos"].append(f"protocolo fuera del catálogo: {protocolo['nombre']!r}")
                continue
            puerto, transporte = CATALOGO[nombre]
            if protocolo["puerto"] != puerto:
                secciones["Protocolos"].append(f"{nombre} debe usar el puerto {puerto}")
            if str(protocolo["transporte"]).upper() != transporte:
                secciones["Protocolos"].append(f"{nombre} debe ir sobre {transporte}")
            else:
                transportes.add(transporte)
            if not es_entero(protocolo["vlan_id"]) or (ids and protocolo["vlan_id"] not in ids):
                secciones["Protocolos"].append(f"{nombre} apunta a una VLAN inexistente")
            if nombre == "SSH":
                hay_ssh = True
                if protocolo["vlan_id"] == vlan_admin:
                    hay_ssh_admin = True
        if "TCP" not in transportes or "UDP" not in transportes:
            secciones["Protocolos"].append("incluye al menos un protocolo TCP y uno UDP")
        if not hay_ssh:
            secciones["Protocolos"].append("falta SSH")
        elif not hay_ssh_admin:
            secciones["Protocolos"].append("SSH debe estar en la VLAN de administración")
    return secciones


def normalizar_conteo(conteo):
    if not isinstance(conteo, dict):
        raise TypeError("dispositivos_por_vlan debe ser un diccionario")
    normal = {}
    for clave, valor in conteo.items():
        if isinstance(clave, str) and clave.isdigit():
            clave = int(clave)
        if not es_entero(clave) or not es_entero(valor):
            raise TypeError(f"conteo inválido: {clave!r} -> {valor!r}")
        normal[clave] = valor
    return normal


def importar_app():
    try:
        return importlib.import_module("app"), None
    except Exception as exc:
        return None, exc


def evaluar_fase_1(fase, app, error):
    if error:
        fase.agregar(False, "Importar app.py", explicar(error))
        return
    campus = getattr(app, "CAMPUS", None)
    vlan_admin = getattr(app, "VLAN_ADMIN", None)
    vlans = getattr(app, "VLANS", None)
    dispositivos = getattr(app, "DISPOSITIVOS", None)
    protocolos = getattr(app, "PROTOCOLOS", None)
    for nombre, errores in revisar_contenido(
        campus, vlan_admin, vlans, dispositivos, protocolos
    ).items():
        marcar(fase, nombre, errores)

    if not isinstance(dispositivos, list) or not dispositivos:
        fase.agregar(False, "dispositivos_en_vlan", "primero llena DISPOSITIVOS")
    else:
        try:
            vlan_id = dispositivos[0]["vlan_id"]
            esperado = [
                d["hostname"]
                for d in dispositivos
                if isinstance(d, dict) and d.get("vlan_id") == vlan_id
            ]
            obtenido = app.dispositivos_en_vlan(vlan_id)
            libre = next(
                candidato
                for candidato in range(4094, 4000, -1)
                if all(not isinstance(d, dict) or d.get("vlan_id") != candidato for d in dispositivos)
            )
            vacio = app.dispositivos_en_vlan(libre)
        except Exception as exc:
            fase.agregar(False, "dispositivos_en_vlan", explicar(exc))
        else:
            if obtenido != esperado:
                fase.agregar(
                    False,
                    "dispositivos_en_vlan",
                    f"se esperaba {recorte(esperado)} y llegó {recorte(obtenido)}",
                )
            elif vacio != []:
                fase.agregar(False, "dispositivos_en_vlan", "una VLAN sin equipos debe regresar []")
            else:
                fase.agregar(True, "dispositivos_en_vlan")

    try:
        resumen = app.resumen_campus()
    except Exception as exc:
        fase.agregar(False, "resumen_campus", explicar(exc))
        return
    if not isinstance(resumen, dict):
        fase.agregar(False, "resumen_campus", "debe regresar un diccionario")
        return
    errores = []
    esperados = {
        "campus": campus,
        "total_vlans": len(vlans) if isinstance(vlans, list) else None,
        "total_dispositivos": len(dispositivos) if isinstance(dispositivos, list) else None,
        "total_protocolos": len(protocolos) if isinstance(protocolos, list) else None,
    }
    for llave, valor in esperados.items():
        if resumen.get(llave) != valor:
            errores.append(f"{llave} debería ser {valor!r}")
    try:
        conteo = {}
        for dispositivo in dispositivos:
            conteo[dispositivo["vlan_id"]] = conteo.get(dispositivo["vlan_id"], 0) + 1
        if normalizar_conteo(resumen.get("dispositivos_por_vlan")) != conteo:
            errores.append(
                f"dispositivos_por_vlan debería ser {conteo!r} y es {recorte(resumen.get('dispositivos_por_vlan'))}"
            )
    except Exception as exc:
        errores.append(explicar(exc))
    marcar(fase, "resumen_campus", errores)


def evaluar_fase_2(fase, destino, app, error):
    ruta = destino / "inventario.json"
    datos = None
    if not ruta.is_file():
        fase.agregar(False, "inventario.json", "no existe el archivo junto a app.py")
    else:
        try:
            datos = json.loads(leer(ruta))
            fase.agregar(True, "JSON válido")
        except Exception as exc:
            fase.agregar(False, "JSON válido", explicar(exc))
    if isinstance(datos, dict) and all(llave in datos for llave in LLAVES):
        fase.agregar(True, "Estructura")
        for nombre, errores in revisar_contenido(
            datos["campus"],
            datos["vlan_admin"],
            datos["vlans"],
            datos["dispositivos"],
            datos["protocolos"],
        ).items():
            marcar(fase, nombre, errores)
    else:
        fase.agregar(
            False,
            "Estructura",
            "el objeto debe tener campus, vlan_admin, vlans, dispositivos y protocolos",
        )
    if error:
        fase.agregar(False, "cargar_inventario", explicar(error))
        fase.agregar(False, "guardar_inventario", explicar(error))
        return
    if datos is None:
        fase.agregar(False, "cargar_inventario", "el archivo JSON todavía no se puede leer")
    else:
        try:
            cargado = app.cargar_inventario(ruta)
        except Exception as exc:
            fase.agregar(False, "cargar_inventario", explicar(exc))
        else:
            if cargado != datos:
                fase.agregar(False, "cargar_inventario", "no regresó el mismo diccionario del archivo")
            else:
                fase.agregar(True, "cargar_inventario")
    original = {
        "campus": "Gestión",
        "vlan_admin": 40,
        "vlans": [],
        "dispositivos": [],
        "protocolos": [],
    }
    volcado = destino / "_volcado_verificador.json"
    try:
        app.guardar_inventario(volcado, original)
        texto = leer(volcado)
        recuperado = app.cargar_inventario(volcado)
    except Exception as exc:
        fase.agregar(False, "guardar_inventario", explicar(exc))
        return
    if "Gestión" not in texto:
        fase.agregar(
            False,
            "guardar_inventario",
            "los acentos deben guardarse como caracteres (ensure_ascii=False) y en UTF-8",
        )
    elif recuperado != original:
        fase.agregar(False, "guardar_inventario", "cargar no recuperó lo que se guardó")
    else:
        fase.agregar(True, "guardar_inventario")


def tiene_variable(texto, nombre):
    return re.search(r"\{\{\s*" + re.escape(nombre) + r"\s*\}\}", texto) is not None


def evaluar_fase_3(fase, destino, app, error):
    inicio = destino / "templates" / "inicio.html"
    detalle = destino / "templates" / "detalle.html"
    if not inicio.is_file() or not detalle.is_file():
        fase.agregar(False, "Plantillas", "hacen falta templates/inicio.html y templates/detalle.html")
        return
    texto_inicio = leer(inicio)
    texto_detalle = leer(detalle)
    faltan = []
    if not tiene_variable(texto_inicio, "campus"):
        faltan.append("inicio.html debe mostrar {{ campus }}")
    if not tiene_variable(texto_inicio, "resumen"):
        faltan.append("inicio.html debe mostrar {{ resumen }}")
    if not re.search(r"\{%\s*if\s+resumen\b", texto_inicio):
        faltan.append("inicio.html debe ocultar el resumen con {% if resumen %}")
    if not re.search(r"\{%\s*endif\s*%\}", texto_inicio):
        faltan.append("inicio.html debe cerrar el if con {% endif %}")
    if not tiene_variable(texto_detalle, "vlan_id"):
        faltan.append("detalle.html debe mostrar {{ vlan_id }}")
    if not re.search(r"\{%\s*if\s+equipos\b", texto_detalle):
        faltan.append("detalle.html debe ocultar la lista con {% if equipos %}")
    if not re.search(r"\{%\s*for\s+\w+\s+in\s+equipos\s*%\}", texto_detalle):
        faltan.append("detalle.html debe recorrer los equipos con {% for ... in equipos %}")
    if not re.search(r"\{%\s*endfor\s*%\}", texto_detalle):
        faltan.append("detalle.html debe cerrar el for con {% endfor %}")
    marcar(fase, "Plantillas con if y for", faltan)
    if error or app is None:
        fase.agregar(False, "Rutas", explicar(error) if error else "no se importó app.py")
        return
    aplicacion = getattr(app, "app", None)
    if aplicacion is None or not hasattr(app, "render_template"):
        fase.agregar(False, "Rutas", "app.py debe definir app y usar render_template")
        return

    registro = []
    original = app.render_template

    def envoltura(plantilla, **kwargs):
        registro.append((plantilla, kwargs))
        return original(plantilla, **kwargs)

    app.render_template = envoltura
    aplicacion.testing = True
    cliente = aplicacion.test_client()
    try:
        respuesta = cliente.get("/")
        cuerpo = respuesta.get_data(as_text=True)
        llamada = next((item for item in registro if item[0] == "inicio.html"), None)
        if respuesta.status_code != 200:
            fase.agregar(False, "GET /", f"se esperaba HTTP 200 y llegó {respuesta.status_code}")
        elif llamada is None:
            fase.agregar(False, "GET /", "la ruta debe renderizar templates/inicio.html")
        elif llamada[1].get("campus") != app.CAMPUS or llamada[1].get("resumen") != app.resumen_campus():
            fase.agregar(
                False,
                "GET /",
                "pasa campus=CAMPUS y resumen=resumen_campus() a la plantilla",
            )
        elif not isinstance(app.CAMPUS, str) or app.CAMPUS not in cuerpo:
            fase.agregar(False, "GET /", "la página no muestra el texto de CAMPUS")
        else:
            fase.agregar(True, "GET /")

        dispositivos = app.DISPOSITIVOS if isinstance(app.DISPOSITIVOS, list) else []
        if not dispositivos or not isinstance(dispositivos[0], dict):
            fase.agregar(False, "GET /vlan/<id>", "primero llena DISPOSITIVOS para probar la página")
            return
        vlan_id = dispositivos[0]["vlan_id"]
        esperados = app.dispositivos_en_vlan(vlan_id)
        registro.clear()
        respuesta = cliente.get(f"/vlan/{vlan_id}")
        cuerpo = respuesta.get_data(as_text=True)
        llamada = next((item for item in registro if item[0] == "detalle.html"), None)
        if respuesta.status_code != 200:
            fase.agregar(False, "GET /vlan/<id>", f"se esperaba HTTP 200 y llegó {respuesta.status_code}")
        elif llamada is None:
            fase.agregar(False, "GET /vlan/<id>", "la ruta debe renderizar templates/detalle.html")
        elif llamada[1].get("vlan_id") != vlan_id or llamada[1].get("equipos") != esperados:
            fase.agregar(
                False,
                "GET /vlan/<id>",
                "pasa vlan_id y equipos=dispositivos_en_vlan(vlan_id)",
            )
        elif not esperados or esperados[0] not in cuerpo:
            fase.agregar(False, "GET /vlan/<id>", "la página no muestra los hostnames")
        else:
            fase.agregar(True, "GET /vlan/<id>")
    finally:
        app.render_template = original


def imprimir_fase(fase):
    print(f"Fase {fase.numero} — {fase.titulo}")
    if not fase.puntos:
        print("  [no] Sin resultados")
    for ok, nombre, detalle in fase.puntos:
        marca = "ok" if ok else "no"
        if detalle and not ok:
            print(f"  [{marca}] {nombre}: {detalle}")
        else:
            print(f"  [{marca}] {nombre}")
    print(fase.resumen())
    print()


def evaluar(destino):
    for nombre in ("app",):
        sys.modules.pop(nombre, None)
    sys.path.insert(0, str(destino))
    fases = [
        Fase(1, "Listas y diccionarios en app.py"),
        Fase(2, "Archivo JSON"),
        Fase(3, "Dos plantillas con variables"),
    ]
    try:
        ruta_json = destino / "inventario.json"
        respaldo = ruta_json.read_bytes() if ruta_json.is_file() else None
        app, error = importar_app()
        if respaldo is not None:
            ruta_json.write_bytes(respaldo)
        evaluar_fase_1(fases[0], app, error)
        evaluar_fase_2(fases[1], destino, app, error)
        evaluar_fase_3(fases[2], destino, app, error)
    finally:
        sys.modules.pop("app", None)
        try:
            sys.path.remove(str(destino))
        except ValueError:
            pass
    return fases


def main(argv):
    configurar_salida()
    if len(argv) != 2:
        print("Uso: python verificar.py <carpeta>")
        print("Ejemplo: python verificar.py plantilla")
        return 2
    carpeta = Path(argv[1]).resolve()
    if not carpeta.is_dir():
        print("No es una carpeta:", carpeta)
        return 2
    print("Carpeta:", carpeta)
    print()
    anterior = Path.cwd()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "entrega"
            shutil.copytree(
                carpeta,
                destino,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv", "venv"),
            )
            os.chdir(destino)
            try:
                fases = evaluar(destino)
            finally:
                os.chdir(anterior)
    except Exception:
        os.chdir(anterior)
        traceback.print_exc()
        return 1
    for fase in fases:
        imprimir_fase(fase)
    aprobadas = sum(1 for fase in fases if fase.aprobada)
    if aprobadas >= 2:
        print(f"Examen: APROBADO ({aprobadas} de 3 fases)")
        return 0
    print(f"Examen: NO APROBADO ({aprobadas} de 3 fases)")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
