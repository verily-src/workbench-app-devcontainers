FROM nginx:1.25-alpine

# Copy configuration files
COPY nginx.conf /etc/nginx/nginx.conf
COPY default.conf /etc/nginx/conf.d/default.conf

# Copy static assets (JavaScript and CSS for policy interceptor)
COPY static /usr/share/nginx/html/aou-static

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
