FROM node:18-alpine

WORKDIR /app

COPY package*.json ./

RUN rm -rf node_modules && \
    npm cache clean --force && \
    npm install

COPY . .

EXPOSE 3000

CMD ["npm", "start"]
