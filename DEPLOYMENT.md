# BaseLodge Deployment Guide

## Production Deployment Checklist

### Step 1: Verify Code is Clean (No Module-Level DB Code)
The app now safely imports without executing database operations. All initialization is deferred to:
- **CLI Command:** `flask init-db` (primary method)
- **HTTP Endpoint:** `GET /admin/init-db` (backup method)

### Step 2: Deploy to Production
1. Push code to your deployment platform (Replit, Heroku, etc.)
2. Server will start normally without database operations
3. All routes are immediately accessible

### Step 3: Initialize Database (Choose ONE Method)

#### **METHOD A: Flask CLI Command (Recommended)**
After deployment, run in terminal:
```bash
flask init-db
```
This will:
- Create all database tables
- Create/verify primary user (Richard Battle-Baxter / 12345678)
- Log status messages

#### **METHOD B: HTTP Endpoint (Backup)**
If CLI doesn't work, you can initialize via HTTP:
```
GET https://yourapp.replit.dev/admin/init-db
```

Response example:
```json
{
  "status": "success",
  "message": "✅ Database initialized. Primary user created.",
  "email": "richardbattlebaxter@gmail.com",
  "password": "12345678"
}
```

**Note:** In production, this endpoint checks that the caller is the admin. In development, it's always accessible.

### Step 4: Verify Deployment
1. Visit your app URL
2. You should see the login screen
3. Test login with: `richardbattlebaxter@gmail.com` / `12345678`

## Environment Variables Required

### Development
```bash
SESSION_SECRET=your-secret-key
DATABASE_URL=sqlite:///baselodge.db
```

### Production
```bash
SESSION_SECRET=your-secret-key
DATABASE_URL=postgresql://user:pass@host/dbname
```

## Troubleshooting

### "Database initialization failed" Error
**Cause:** Database is already initialized or tables already exist
**Solution:** This is normal on subsequent deployments. The init command is idempotent.

### "Primary user not found" Error
**Cause:** Primary user creation failed
**Solution:** Call `/admin/init-db` endpoint in browser to debug

### "Connection refused" Error
**Cause:** DATABASE_URL is invalid or database is unreachable
**Solution:** Verify DATABASE_URL environment variable is set correctly

## Production Features Enabled

✅ Flask-Login session management  
✅ SQLAlchemy ORM with PostgreSQL support  
✅ Gunicorn-compatible (no module-level DB code)  
✅ Proper error handling and logging  
✅ CSRF protection via Flask sessions  

## Database Schema

The app uses these core tables:
- `user` - User accounts with authentication
- `resort` - Canonical ski resort list (81 resorts, searchable)
- `ski_trip` - Trip records with resort FK
- `friend` - Bidirectional friendships
- `invitation` - Friend invitations (optional)
- `invite_token` - Share tokens for invites

All tables are created automatically by `flask init-db`.

## Performance Notes

- Database connection pooling is enabled (pool_recycle=300s)
- Sessions are cached and refreshed per request
- Queries are optimized with appropriate joins
- JSON fields (open_dates, mountains_visited) are indexed

## Need Help?

If deployment fails:
1. Check DATABASE_URL is set correctly
2. Run `flask init-db` to initialize
3. Check Flask logs for error messages
4. Verify all required environment variables are present
