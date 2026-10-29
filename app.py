"""Inventario de red del campus.

Fase 1: variables, listas, diccionarios y funciones (no son rutas).
Fase 2: leer y escribir inventario.json.
Fase 3: las rutas solo muestran esas variables en las plantillas.

Ejecuta este archivo desde la carpeta plantilla:

    python app.py
"""

import json

from flask import Flask, render_template

app = Flask(__name__)

CAMPUS = "Campus Norte"
VLAN_ADMIN = 40

VLANS = [
    {"id": 10, "nombre": "Docentes", "uso": "Equipos del personal docente"},
    {"id": 20, "nombre": "Alumnos", "uso": "Red de laboratorios y aulas"},
    {"id": 40, "nombre": "Gestion", "uso": "Administracion de equipos de red"},
]

DISPOSITIVOS = [
    {"hostname": "rtr-norte", "ip": "10.0.40.1", "tipo": "router", "vlan_id": 40},
    {"hostname": "sw-core", "ip": "10.0.40.2", "tipo": "switch", "vlan_id": 40},
    {"hostname": "srv-dhcp", "ip": "10.0.10.5", "tipo": "servidor", "vlan_id": 10},
    {"hostname": "ap-lab1", "ip": "10.0.20.10", "tipo": "access-point", "vlan_id": 20},
]

PROTOCOLOS = [
    {"nombre": "SSH", "puerto": 22, "transporte": "TCP", "vlan_id": 40},
    {"nombre": "DNS", "puerto": 53, "transporte": "UDP", "vlan_id": 10},
    {"nombre": "HTTPS", "puerto": 443, "transporte": "TCP", "vlan_id": 20},
]


def dispositivos_en_vlan(vlan_id):
    """Regresa los hostnames, en orden, de los equipos de esa VLAN."""
    return [d["hostname"] for d in DISPOSITIVOS if d["vlan_id"] == vlan_id]


def resumen_campus():
    """Regresa el diccionario con campus, totales y dispositivos_por_vlan."""
    por_vlan = {}
    for d in DISPOSITIVOS:
        por_vlan[d["vlan_id"]] = por_vlan.get(d["vlan_id"], 0) + 1
    return {
        "campus": CAMPUS,
        "total_vlans": len(VLANS),
        "total_dispositivos": len(DISPOSITIVOS),
        "total_protocolos": len(PROTOCOLOS),
        "dispositivos_por_vlan": por_vlan,
    }


def cargar_inventario(ruta):
    """Lee el JSON y regresa el diccionario."""
    with open(ruta, encoding="utf-8") as archivo:
        return json.load(archivo)


def guardar_inventario(ruta, inventario):
    """Escribe el diccionario como JSON, con acentos reales."""
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(inventario, archivo, ensure_ascii=False, indent=2)


@app.get("/")
def inicio():
    return render_template("inicio.html", campus=CAMPUS, resumen=resumen_campus())


@app.get("/vlan/<int:vlan_id>")
def detalle(vlan_id):
    return render_template(
        "detalle.html", vlan_id=vlan_id, equipos=dispositivos_en_vlan(vlan_id)
    )


if __name__ == "__main__":
    app.run(debug=True)
