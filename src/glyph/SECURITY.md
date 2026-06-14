# Security Considerations for Glyph Annotation Tool

## Threat Model

### Protection Layers

1. **Workbench Authentication** (Primary Defense)
   - Apps are NOT publicly accessible
   - Requires Verily Workbench login
   - IAM-based access control
   - Apps run in isolated GCP VPC

2. **Application Security** (Secondary Defense)
   - Protects against malicious authorized users
   - Prevents accidental vulnerabilities
   - Defends against compromised accounts

## Current Vulnerabilities

### 1. Path Traversal (CRITICAL)

**Issue**: `/images/<path:filename>` endpoint allows directory traversal

**Attack**:
```bash
curl http://app/images/../../app_demo.py
curl http://app/images/../../../etc/passwd
```

**Fix**:
```python
from werkzeug.utils import secure_filename
from pathlib import Path

@app.route('/images/<path:filename>')
def serve_image(filename):
    safe_filename = secure_filename(filename)
    filepath = IMAGES_DIR / safe_filename
    
    # Ensure path stays within IMAGES_DIR
    if not filepath.resolve().is_relative_to(IMAGES_DIR.resolve()):
        return "Access denied", 403
    
    return send_from_directory(IMAGES_DIR, safe_filename)
```

---

### 2. No Input Validation (MEDIUM)

**Issue**: API accepts any JSON without validation

**Attack**:
- JSON bomb (huge payloads)
- Invalid task_ids
- Malformed annotation data

**Fix**:
```python
MAX_PAYLOAD_SIZE = 1_000_000  # 1MB
MAX_BBOXES = 100

@app.route('/api/annotations', methods=['POST'])
def save_annotation():
    # Validate content size
    if request.content_length and request.content_length > MAX_PAYLOAD_SIZE:
        return jsonify({'error': 'Payload too large'}), 413
    
    data = request.json
    
    # Validate structure
    if not data or 'task_id' not in data or 'annotation_data' not in data:
        return jsonify({'error': 'Missing required fields'}), 400
    
    # Validate task exists
    if not any(t['task_id'] == data['task_id'] for t in TASKS):
        return jsonify({'error': 'Task not found'}), 404
    
    # Validate bbox count
    bboxes = data['annotation_data'].get('bboxes', [])
    if len(bboxes) > MAX_BBOXES:
        return jsonify({'error': 'Too many bboxes'}), 400
    
    # Continue...
```

---

### 3. Debug Mode Enabled (CRITICAL)

**Issue**: `app.run(debug=True)` in production

**Impact**:
- Exposes interactive debugger console
- Allows arbitrary code execution
- Leaks stack traces and code paths

**Fix**:
```python
# app_demo.py (development only)
debug_mode = os.getenv('FLASK_ENV') == 'development'
app.run(host='0.0.0.0', port=port, debug=debug_mode)

# Production: Use Gunicorn (already in Dockerfile)
# gunicorn --bind 0.0.0.0:8080 --workers 2 app:app
```

---

### 4. No Rate Limiting (MEDIUM)

**Issue**: No protection against API abuse

**Attack**:
```bash
# Flood server with requests
while true; do 
  curl -X POST http://app/api/annotations -d '{"task_id":"x",...}' 
done
```

**Fix**:
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["1000 per day", "100 per hour"],
    storage_uri="memory://"
)

@app.route('/api/annotations', methods=['POST'])
@limiter.limit("20 per minute")
def save_annotation():
    # ...
```

Add to `requirements.txt`:
```
Flask-Limiter==3.5.0
```

---

### 5. No Content Security Policy (LOW)

**Issue**: No CSP headers to prevent XSS

**Fix**:
```python
from flask import Flask
from flask_talisman import Talisman

app = Flask(__name__)

# Add security headers
Talisman(app, 
    content_security_policy={
        'default-src': "'self'",
        'script-src': ["'self'", 'cdnjs.cloudflare.com'],
        'style-src': ["'self'", "'unsafe-inline'"],
        'img-src': ["'self'", 'data:'],
    },
    force_https=False  # Workbench proxy handles HTTPS
)
```

Add to `requirements.txt`:
```
flask-talisman==1.1.0
```

---

### 6. In-Memory Storage (AVAILABILITY)

**Issue**: Data lost on container restart

**Risk**: Annotation loss, not a security issue but impacts availability

**Fix**: Use production mode with BigQuery for persistence

---

## Recommended Security Architecture

### Defense in Depth

```
Internet
    ↓
❌ Blocked (no public access)
    ↓
Verily Workbench IAM Auth
    ↓
✅ Authenticated User
    ↓
Workbench Proxy (HTTPS, auth headers)
    ↓
Docker Network (app-network)
    ↓
Flask App Container
    ├─ Rate Limiting (Flask-Limiter)
    ├─ Input Validation (schemas)
    ├─ Path Sanitization (secure_filename)
    ├─ CSRF Protection (Flask-WTF)
    └─ Security Headers (Talisman)
```

---

## Quick Security Fixes

### Immediate (Do Now)

1. **Disable debug mode**:
   ```python
   app.run(host='0.0.0.0', port=port, debug=False)
   ```

2. **Fix path traversal**:
   ```python
   from werkzeug.utils import secure_filename
   filename = secure_filename(request.args.get('filename'))
   ```

3. **Add input validation**:
   ```python
   if not data or 'task_id' not in data:
       return jsonify({'error': 'Invalid input'}), 400
   ```

### Short-term (This Week)

4. Add rate limiting (Flask-Limiter)
5. Add content size limits
6. Add security headers (Talisman)
7. Use Gunicorn in production (already in Dockerfile, just update docker-compose)

### Long-term (Future Enhancement)

8. Add audit logging (who annotated what, when)
9. Add CSRF protection (Flask-WTF)
10. Add user session management
11. Implement role-based access (admin vs annotator)

---

## Production Deployment Checklist

- [ ] `DEBUG=False` in environment
- [ ] Use Gunicorn (not Flask dev server)
- [ ] Rate limiting enabled
- [ ] Input validation on all endpoints
- [ ] Path traversal protection
- [ ] Security headers (CSP, HSTS, etc.)
- [ ] BigQuery backend (not in-memory)
- [ ] Audit logging enabled
- [ ] Regular dependency updates
- [ ] Monitor for security advisories

---

## Testing Security

### Manual Tests

```bash
# Test path traversal
curl http://localhost:8085/images/../app_demo.py
# Should return 403 Forbidden

# Test payload size limit
curl -X POST http://localhost:8085/api/annotations \
  -H "Content-Type: application/json" \
  -d @huge_file.json
# Should return 413 Payload Too Large

# Test rate limiting
for i in {1..100}; do 
  curl http://localhost:8085/api/tasks
done
# Should return 429 Too Many Requests after limit
```

### Automated Security Scanning

```bash
# Install bandit (Python security linter)
pip install bandit

# Scan code for vulnerabilities
bandit -r app.py app_demo.py

# Check dependencies for known vulnerabilities
pip install safety
safety check
```

---

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Flask Security Best Practices](https://flask.palletsprojects.com/en/2.3.x/security/)
- [Google Cloud Security Best Practices](https://cloud.google.com/security/best-practices)
