from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

import feedparser
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, flash, redirect, render_template, request, url_for
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///fiscal.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")

db = SQLAlchemy(app)


class Keyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    value = db.Column(db.String(120), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class FiscalUpdate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    url = db.Column(db.String(600), unique=True, nullable=False)
    source = db.Column(db.String(120), nullable=False)
    published_at = db.Column(db.DateTime, nullable=True)
    keyword_hits = db.Column(db.String(240), nullable=False)
    relevance_score = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="ativo")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


DEFAULT_FEEDS = [
    "https://www.gov.br/receitafederal/pt-br/assuntos/noticias/rss",
    "https://www.gov.br/economia/pt-br/assuntos/noticias/rss",
    "https://www.contabeis.com.br/rss/noticias.xml",
]


def parse_date(entry: dict) -> datetime | None:
    if entry.get("published_parsed"):
        return datetime(*entry.published_parsed[:6])
    if entry.get("updated_parsed"):
        return datetime(*entry.updated_parsed[:6])
    return None


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def ai_keyword_score(text: str, keywords: Iterable[str]) -> tuple[float, list[str]]:
    """Pontuação simples de relevância baseada em similaridade léxica.

    É um classificador leve para protótipo visual.
    """
    cleaned = normalize_text(text)
    if not cleaned:
        return 0.0, []

    hits: list[str] = []
    score = 0.0
    for keyword in keywords:
        key = normalize_text(keyword)
        if not key:
            continue

        pattern = rf"\b{re.escape(key)}\b"
        if re.search(pattern, cleaned):
            hits.append(keyword)
            score += 1.0
            continue

        if key in cleaned:
            hits.append(keyword)
            score += 0.75

    density = min(1.0, len(hits) / max(1, len(list(keywords))))
    final_score = round((score * 0.7) + (density * 0.3), 2)
    return final_score, hits


def collect_updates() -> int:
    keywords = [k.value for k in Keyword.query.order_by(Keyword.value).all()]
    if not keywords:
        return 0

    total_inserted = 0
    for feed in DEFAULT_FEEDS:
        parsed = feedparser.parse(feed)
        for entry in parsed.entries[:50]:
            title = entry.get("title", "Sem título")
            summary = entry.get("summary", "")
            full_text = f"{title} {summary}"
            score, hits = ai_keyword_score(full_text, keywords)
            if score < 1 or not hits:
                continue

            url = entry.get("link")
            if not url:
                continue

            if FiscalUpdate.query.filter_by(url=url).first():
                continue

            item = FiscalUpdate(
                title=title[:300],
                summary=summary,
                url=url,
                source=parsed.feed.get("title", "Fonte não informada")[:120],
                published_at=parse_date(entry),
                keyword_hits=", ".join(hits)[:240],
                relevance_score=score,
            )
            db.session.add(item)
            total_inserted += 1

    if total_inserted:
        db.session.commit()
    return total_inserted


@app.route("/", methods=["GET"])
def index():
    keywords = Keyword.query.order_by(Keyword.value).all()
    updates = FiscalUpdate.query.order_by(FiscalUpdate.created_at.desc()).limit(100).all()

    total_updates = db.session.query(func.count(FiscalUpdate.id)).scalar()
    active_updates = db.session.query(func.count(FiscalUpdate.id)).filter_by(status="ativo").scalar()
    discontinued_updates = db.session.query(func.count(FiscalUpdate.id)).filter_by(status="descontinuado").scalar()

    return render_template(
        "index.html",
        keywords=keywords,
        updates=updates,
        stats={
            "total": total_updates,
            "active": active_updates,
            "discontinued": discontinued_updates,
        },
    )


@app.route("/keywords", methods=["POST"])
def add_keyword():
    value = request.form.get("value", "").strip()
    if not value:
        flash("Informe uma palavra-chave válida.", "warning")
        return redirect(url_for("index"))

    exists = Keyword.query.filter(func.lower(Keyword.value) == value.lower()).first()
    if exists:
        flash("Palavra-chave já cadastrada.", "warning")
        return redirect(url_for("index"))

    db.session.add(Keyword(value=value))
    db.session.commit()
    flash("Palavra-chave adicionada com sucesso.", "success")
    return redirect(url_for("index"))


@app.route("/keywords/<int:keyword_id>/delete", methods=["POST"])
def delete_keyword(keyword_id: int):
    keyword = Keyword.query.get_or_404(keyword_id)
    db.session.delete(keyword)
    db.session.commit()
    flash("Palavra-chave removida.", "success")
    return redirect(url_for("index"))


@app.route("/collect", methods=["POST"])
def trigger_collect():
    inserted = collect_updates()
    if inserted:
        flash(f"Coleta automática finalizada: {inserted} nova(s) atualização(ões).", "success")
    else:
        flash("Coleta executada sem novos resultados. Ajuste as palavras-chave.", "info")
    return redirect(url_for("index"))


@app.route("/updates/<int:update_id>/status", methods=["POST"])
def toggle_status(update_id: int):
    update = FiscalUpdate.query.get_or_404(update_id)
    next_status = request.form.get("status")
    if next_status not in {"ativo", "descontinuado"}:
        flash("Status inválido.", "danger")
        return redirect(url_for("index"))

    update.status = next_status
    db.session.commit()
    flash("Status da notícia atualizado.", "success")
    return redirect(url_for("index"))


def ensure_seed_keywords() -> None:
    if Keyword.query.count() == 0:
        for default_kw in ["ICMS", "ISS", "Simples Nacional", "SPED", "EFD", "reforma tributária"]:
            db.session.add(Keyword(value=default_kw))
        db.session.commit()


def setup_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(collect_updates, "interval", minutes=60, id="fiscal-auto-collector", replace_existing=True)
    scheduler.start()
    return scheduler


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_seed_keywords()

    setup_scheduler()
    app.run(host="0.0.0.0", port=5000, debug=True)
