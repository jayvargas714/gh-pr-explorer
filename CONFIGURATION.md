# Configuration Guide

This guide explains how to configure GitHub PR Explorer for different deployment scenarios.

## Quick Start (Default - Localhost Only)

By default, the application runs on localhost:

- **Backend**: http://127.0.0.1:5050
- **Frontend Dev**: http://localhost:3000

No configuration needed for local development.

---

## Network Access Configuration

To access the application from other devices on your network (e.g., from your phone or another computer):

### Step 1: Find Your IP Address

**On macOS/Linux:**
```bash
ifconfig | grep "inet " | grep -v 127.0.0.1
```

**On Windows:**
```bash
ipconfig
```

Look for your local IP address (usually starts with `192.168.x.x` or `10.0.x.x`)

Example: `192.168.1.100`

### Step 2: Configure Backend

The backend `config.json` is already configured to listen on all network interfaces:

```json
{
  "port": 5050,
  "host": "0.0.0.0",
  "debug": false,
  "default_per_page": 30,
  "cache_ttl_seconds": 300
}
```

**Configuration Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `port` | 5050 | Port the Flask server listens on |
| `host` | 0.0.0.0 | Host to bind to (`0.0.0.0` = all interfaces, `127.0.0.1` = localhost only) |
| `debug` | false | Enable Flask debug mode (don't use in production) |
| `default_per_page` | 30 | Default number of results per page for API endpoints |
| `cache_ttl_seconds` | 300 | Cache time-to-live in seconds (5 minutes) |

### Step 3: Configure Frontend (Development Mode)

Create a `.env` file in the `frontend/` directory:

```bash
cd frontend
cp .env.example .env
```

Edit `.env` and set your IP address:

```env
# Use your machine's local IP address
VITE_BACKEND_HOST=192.168.1.100
VITE_BACKEND_PORT=5050
VITE_PORT=3000
```

### Step 4: Start the Application

**Terminal 1 - Backend:**
```bash
python app.py
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

### Step 5: Access from Network

You can now access the application from any device on your network:

- **From your computer**: http://192.168.1.100:3000
- **From other devices**: http://192.168.1.100:3000

Replace `192.168.1.100` with your actual IP address.

---

## Production Deployment

For production, build the frontend and serve everything from Flask:

### Step 1: Build Frontend

```bash
cd frontend
npm run build
```

This creates optimized static files in `frontend/dist/`

### Step 2: Configure Backend for Production

Update `config.json`:

```json
{
  "port": 5050,
  "host": "0.0.0.0",
  "debug": false,
  "default_per_page": 30,
  "cache_ttl_seconds": 300
}
```

### Step 3: Start Backend

```bash
python app.py
```

Flask will automatically serve the built frontend from `frontend/dist/`

### Step 4: Access Production Build

Access the application at: http://192.168.1.100:5050

---

## Firewall Configuration

If you can't access the application from other devices:

**macOS:**
```bash
# Allow incoming connections on port 5050
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add $(which python3)
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp $(which python3)
```

**Linux (ufw):**
```bash
sudo ufw allow 5050/tcp
sudo ufw allow 3000/tcp  # If using dev server
```

**Windows:**
- Go to Windows Defender Firewall
- Click "Allow an app through firewall"
- Add Python and allow on Private networks

---

## Advanced Configuration

### Custom Ports

**Backend:**
Edit `config.json`:
```json
{
  "port": 8080,
  "host": "0.0.0.0"
}
```

**Frontend Dev Server:**
Edit `frontend/.env`:
```env
VITE_BACKEND_PORT=8080
VITE_PORT=4000
```

### HTTPS (Production)

For HTTPS, use a reverse proxy like Nginx or Caddy:

**Nginx Example:**
```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:5050;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Environment Variables

All available frontend environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_BACKEND_HOST` | 127.0.0.1 | Backend server host/IP |
| `VITE_BACKEND_PORT` | 5050 | Backend server port |
| `VITE_PORT` | 3000 | Frontend dev server port |

---

## Troubleshooting

### Can't access from other devices

1. **Check firewall** - Ensure ports are open
2. **Check IP address** - Use `ifconfig` or `ipconfig` to verify
3. **Check network** - Ensure devices are on the same network
4. **Check config** - Verify `host: "0.0.0.0"` in config.json

### Frontend can't reach backend

1. **Check backend is running** - Visit http://192.168.1.100:5050/api/user
2. **Check environment variables** - Verify `.env` has correct VITE_BACKEND_HOST
3. **Restart dev server** - Changes to `.env` require restart
4. **Check browser console** - Look for CORS or network errors

### CORS errors

Flask backend allows all origins by default. If you see CORS errors:

1. Check that `changeOrigin: true` is set in Vite proxy config
2. Verify backend is accessible directly (not just through proxy)

---

## Security Considerations

### Development

- Default configuration is suitable for local network use
- Don't expose to the internet without authentication
- Use `debug: false` in production

### Production

- Use HTTPS with a reverse proxy
- Implement authentication if exposing to internet
- Set appropriate CORS policies
- Use environment variables for sensitive config
- Keep `debug: false` always

---

## Example Configurations

### Local Development Only

**config.json:**
```json
{
  "port": 5050,
  "host": "127.0.0.1",
  "debug": true
}
```

**frontend/.env:**
```env
VITE_BACKEND_HOST=127.0.0.1
VITE_BACKEND_PORT=5050
```

### Home Network Access

**config.json:**
```json
{
  "port": 5050,
  "host": "0.0.0.0",
  "debug": false
}
```

**frontend/.env:**
```env
VITE_BACKEND_HOST=192.168.1.100
VITE_BACKEND_PORT=5050
```

### Production with Custom Port

**config.json:**
```json
{
  "port": 8080,
  "host": "0.0.0.0",
  "debug": false,
  "cache_ttl_seconds": 600
}
```

No frontend .env needed (serves from dist/)

---

## Need Help?

- Check logs in terminal where Flask is running
- Check browser console for frontend errors
- Verify network connectivity with `ping 192.168.1.100`
- Test backend directly: `curl http://192.168.1.100:5050/api/user`
