FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json /app/
RUN npm ci --prefer-offline

COPY . /app

EXPOSE 5173
CMD ["npm", "run", "dev"]
