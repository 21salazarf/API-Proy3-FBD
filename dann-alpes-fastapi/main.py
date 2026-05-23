from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
from typing import Optional
import os
import certifi

app = FastAPI(title="Dann-Alpes API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = os.environ.get("MONGO_URI")
DB_NAME   = "ISIS2304I29202610"
COL_NAME  = "resenas"

client = MongoClient(MONGO_URI)
db     = client[DB_NAME]
col    = db[COL_NAME]

def parse_doc(doc):
    """Convierte ObjectId a string para poder serializar a JSON."""
    doc["_id"] = str(doc["_id"])
    return doc


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "dann-alpes API ok"}


# ── RF1: Crear reseña ─────────────────────────────────────────────────────────
@app.post("/resenas")
def crear_resena(body: dict):
    id_hotel    = int(body.get("id_hotel_oracle"))
    id_cliente  = str(body.get("id_cliente_oracle"))
    calificacion = int(body.get("calificacion"))
    comentario  = str(body.get("comentario"))

    if not (1 <= calificacion <= 5):
        raise HTTPException(status_code=400, detail="Calificacion debe estar entre 1 y 5")

    existe = col.find_one({
        "id_hotel_oracle":   id_hotel,
        "id_cliente_oracle": id_cliente,
        "estado": {"$ne": "eliminada"}
    })
    if existe:
        raise HTTPException(status_code=409, detail="El cliente ya tiene una reseña para este hotel.")

    doc = {
        "id_hotel_oracle":   id_hotel,
        "id_cliente_oracle": id_cliente,
        "calificacion":      calificacion,
        "comentario":        comentario,
        "fecha":             datetime.utcnow(),
        "estado":            "publicada",
        "destacada":         False,
        "usuarios_votantes": []
    }
    result = col.insert_one(doc)
    return {"insertedId": str(result.inserted_id)}


# ── RF2: Editar reseña ────────────────────────────────────────────────────────
@app.put("/resenas/{resena_id}")
def editar_resena(resena_id: str, body: dict):
    update = {}
    if "calificacion" in body:
        cal = int(body["calificacion"])
        if not (1 <= cal <= 5):
            raise HTTPException(status_code=400, detail="Calificacion debe estar entre 1 y 5")
        update["calificacion"] = cal
    if "comentario" in body:
        update["comentario"] = str(body["comentario"])

    result = col.update_one({"_id": ObjectId(resena_id)}, {"$set": update})
    return {"modifiedCount": result.modified_count}


# ── RF3: Eliminar reseña (cliente) ────────────────────────────────────────────
@app.delete("/resenas/{resena_id}")
def eliminar_resena_cliente(resena_id: str):
    result = col.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {"estado": "eliminada"}}
    )
    return {"modifiedCount": result.modified_count}


# ── RF4: Consultar reseñas de un hotel ───────────────────────────────────────
@app.get("/resenas/hotel/{id_hotel}")
def get_resenas_hotel(id_hotel: int, orden: str = "fecha", pagina: int = 1, por_pagina: int = 10):
    sort_field = "fecha" if orden != "utilidad" else "votos_utilidad"
    skip = (pagina - 1) * por_pagina

    destacada = col.find_one({"id_hotel_oracle": id_hotel, "estado": "publicada", "destacada": True})

    pipeline = [
        {"$match": {"id_hotel_oracle": id_hotel, "estado": "publicada"}},
        {"$addFields": {"votos_utilidad": {"$size": {"$ifNull": ["$usuarios_votantes", []]}}}},
        {"$sort": {sort_field: -1}},
        {"$skip": skip},
        {"$limit": por_pagina}
    ]
    resenas = [parse_doc(r) for r in col.aggregate(pipeline)]

    return {
        "destacada": parse_doc(destacada) if destacada else None,
        "resenas":   resenas
    }


# ── RF5: Marcar reseña como útil ─────────────────────────────────────────────
@app.post("/resenas/{resena_id}/util")
def marcar_util(resena_id: str, body: dict):
    id_cliente = str(body.get("id_cliente_oracle"))
    resena = col.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada.")
    if id_cliente in (resena.get("usuarios_votantes") or []):
        raise HTTPException(status_code=409, detail="El usuario ya votó esta reseña.")

    result = col.update_one(
        {"_id": ObjectId(resena_id)},
        {"$addToSet": {"usuarios_votantes": id_cliente}}
    )
    return {"modifiedCount": result.modified_count}


# ── RF6: Historial de reseñas propias ────────────────────────────────────────
@app.get("/resenas/cliente/{id_cliente}")
def get_resenas_cliente(id_cliente: str, orden: str = "fecha"):
    sort_field = "id_hotel_oracle" if orden == "hotel" else "fecha"
    sort_dir   = 1 if orden == "hotel" else -1

    pipeline = [
        {"$match": {"id_cliente_oracle": id_cliente}},
        {"$addFields": {"votos_utilidad": {"$size": {"$ifNull": ["$usuarios_votantes", []]}}}},
        {"$sort": {sort_field: sort_dir}}
    ]
    resenas = [parse_doc(r) for r in col.aggregate(pipeline)]
    return resenas


# ── RF7: Responder reseña (admin) ─────────────────────────────────────────────
@app.post("/resenas/{resena_id}/respuesta")
def responder_resena(resena_id: str, body: dict):
    result = col.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {"respuesta_admin": {
            "usuario_admin":    str(body.get("usuario_admin")),
            "texto":            str(body.get("texto")),
            "fecha_respuesta":  datetime.utcnow()
        }}}
    )
    return {"modifiedCount": result.modified_count}


# ── RF8: Eliminar reseña (admin) ──────────────────────────────────────────────
@app.delete("/resenas/{resena_id}/admin")
def eliminar_resena_admin(resena_id: str):
    result = col.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {"estado": "moderada"}}
    )
    return {"modifiedCount": result.modified_count}


# ── RF9: Destacar reseña (admin) ──────────────────────────────────────────────
@app.post("/resenas/{resena_id}/destacar")
def destacar_resena(resena_id: str):
    resena = col.find_one({"_id": ObjectId(resena_id)})
    if not resena:
        raise HTTPException(status_code=404, detail="Reseña no encontrada.")

    # Quitar destacada anterior del mismo hotel
    col.update_many(
        {"id_hotel_oracle": resena["id_hotel_oracle"], "destacada": True},
        {"$set": {"destacada": False}}
    )
    result = col.update_one(
        {"_id": ObjectId(resena_id)},
        {"$set": {"destacada": True}}
    )
    return {"modifiedCount": result.modified_count}


# ── RFC1: Top 10 hoteles por calificación ─────────────────────────────────────
@app.get("/rfc1")
def rfc1(desde: str = "2026-01-01", hasta: str = "2026-12-31"):
    desde_dt = datetime.fromisoformat(desde)
    hasta_dt = datetime.fromisoformat(hasta)

    pipeline = [
        {"$match": {"fecha": {"$gte": desde_dt, "$lte": hasta_dt}, "estado": "publicada"}},
        {"$group": {
            "_id":                   "$id_hotel_oracle",
            "promedio_calificacion": {"$avg": "$calificacion"},
            "total_resenas":         {"$sum": 1}
        }},
        {"$sort":  {"promedio_calificacion": -1}},
        {"$limit": 10}
    ]
    return list(col.aggregate(pipeline))


# ── RFC2: Evolución mensual de un hotel ───────────────────────────────────────
@app.get("/rfc2/{id_hotel}")
def rfc2(id_hotel: int, anio: int = 2026):
    pipeline = [
        {"$match": {
            "id_hotel_oracle": id_hotel,
            "fecha": {
                "$gte": datetime(anio, 1, 1),
                "$lte": datetime(anio, 12, 31)
            }
        }},
        {"$group": {
            "_id":             {"$month": "$fecha"},
            "promedio_mensual": {"$avg": "$calificacion"},
            "total_resenas":   {"$sum": 1}
        }},
        {"$sort": {"_id": 1}}
    ]
    return list(col.aggregate(pipeline))


# ── RFC3: Perfil comparativo por ciudad ───────────────────────────────────────
@app.get("/rfc3")
def rfc3(hoteles: str = "101,102,103"):
    ids = [int(h) for h in hoteles.split(",") if h.strip()]

    pipeline = [
        {"$match": {"id_hotel_oracle": {"$in": ids}}},
        {"$group": {
            "_id":                   "$id_hotel_oracle",
            "calificacion_promedio": {"$avg": "$calificacion"},
            "total_resenas":         {"$sum": 1},
            "con_respuesta": {"$sum": {"$cond": [{"$ifNull": ["$respuesta_admin", False]}, 1, 0]}},
            "destacadas":    {"$sum": {"$cond": [{"$eq": ["$destacada", True]}, 1, 0]}}
        }},
        {"$project": {
            "_id":                   1,
            "calificacion_promedio": 1,
            "total_resenas":         1,
            "porcentaje_respuestas": {"$multiply": [{"$divide": ["$con_respuesta", "$total_resenas"]}, 100]},
            "porcentaje_destacadas": {"$multiply": [{"$divide": ["$destacadas",    "$total_resenas"]}, 100]}
        }},
        {"$sort": {"calificacion_promedio": -1}}
    ]
    return list(col.aggregate(pipeline))
