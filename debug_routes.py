from flask import Blueprint, jsonify

debug_bp = Blueprint('debug', __name__, url_prefix='/debug')

PASS_OPTIONS = [
    "Epic & Ikon",
    "Epic",
    "Epic Local",
    "Epic 4-day",
    "Ikon",
    "Ikon Base",
    "Ikon Plus",
    "Ikon Session",
    "Loveland",
    "No Pass"
]

@debug_bp.route('/pass-options')
def get_pass_options():
    return jsonify(PASS_OPTIONS)
