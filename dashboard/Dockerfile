FROM node:20-alpine

WORKDIR /app

# Copy package info and install
COPY package.json package-lock.json* ./
RUN npm install

# Copy source
COPY . .

# Expose Vite default port
EXPOSE 5173

# Run development server
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
