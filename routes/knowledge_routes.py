"""
Knowledge Base routes for the multi-tenant CRM application
"""
from flask import Blueprint, request, jsonify, current_app
from models import KnowledgeBaseModel
from utils.auth import token_required

# Create blueprint
knowledge_bp = Blueprint('knowledge', __name__, url_prefix='/api/knowledge')

@knowledge_bp.route('', methods=['GET'])
@token_required
def get_articles():
    """Get knowledge base articles for current tenant"""
    try:
        page = int(request.args.get('page', 1))
        limit = int(request.args.get('limit', 10))
        skip = (page - 1) * limit
        
        tenant_id = request.current_tenant_id
        articles = KnowledgeBaseModel.get_articles_by_tenant(tenant_id, skip, limit)
        
        return jsonify({
            'articles': articles,
            'page': page,
            'limit': limit,
            'total': len(articles)
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Get articles error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@knowledge_bp.route('', methods=['POST'])
@token_required
def create_article():
    """Create a new knowledge base article"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        title = data.get('title', '').strip()
        content = data.get('content', '').strip()
        category = data.get('category', 'General').strip()
        
        if not title:
            return jsonify({'error': 'Article title is required'}), 400
        
        if not content:
            return jsonify({'error': 'Article content is required'}), 400
        
        user_id = request.current_user['_id']
        tenant_id = request.current_tenant_id
        
        article_id = KnowledgeBaseModel.create_article(
            title, content, category, tenant_id, user_id
        )
        
        if article_id:
            return jsonify({
                'message': 'Article created successfully',
                'article_id': article_id
            }), 201
        else:
            return jsonify({'error': 'Failed to create article'}), 500
            
    except Exception as e:
        current_app.logger.error(f"Create article error: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500