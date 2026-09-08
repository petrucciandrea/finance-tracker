FROM node:20-alpine

WORKDIR /app

# Installed separately from the rest of the source so this layer is cached
# and only rebuilt when package.json actually changes, not on every file edit.
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
