# How to Access the stat-expl App in Workbench

The Vite dev server is running on port 8080, but you need to access it through the Workbench proxy URL.

## Quick Steps:

1. **Look at your current browser URL** - It should look something like:
   ```
   https://workbench.verily.com/app/12345678-1234-1234-1234-123456789abc/
   ```

2. **Copy the UUID** (the long string with hyphens after `/app/`)

3. **Access the stat-expl app** by replacing the end of the URL with:
   ```
   https://workbench.verily.com/app/YOUR-UUID-HERE/proxy/8080/dashboard/
   ```

4. **For the test page specifically**:
   ```
   https://workbench.verily.com/app/YOUR-UUID-HERE/proxy/8080/dashboard/test
   ```

## Example:

If your Jupyter URL is:
```
https://workbench.verily.com/app/a1b2c3d4-e5f6-g7h8-i9j0-k1l2m3n4o5p6/
```

Then access stat-expl at:
```
https://workbench.verily.com/app/a1b2c3d4-e5f6-g7h8-i9j0-k1l2m3n4o5p6/proxy/8080/dashboard/
```

And the test page at:
```
https://workbench.verily.com/app/a1b2c3d4-e5f6-g7h8-i9j0-k1l2m3n4o5p6/proxy/8080/dashboard/test
```

## Dev Server Status

The Vite dev server is confirmed running:
- Port: 8080
- Base path: /dashboard/
- Status: ✓ Running

## Available Routes:

- `/dashboard/` → Redirects to Passport page
- `/dashboard/passport` → Passport (placeholder)
- `/dashboard/population` → Population (placeholder)
- `/dashboard/variables` → Variables (placeholder)
- `/dashboard/quality` → Quality (placeholder)
- `/dashboard/hypotheses` → Hypotheses (placeholder)
- `/dashboard/test` → **Test page (use this to verify it works!)**
