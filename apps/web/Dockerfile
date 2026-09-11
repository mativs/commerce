FROM node:22-alpine AS development
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci && chown -R node:node /app
COPY --chown=node:node . .
USER node
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM development AS build
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL
RUN npm run check

FROM scratch AS production
COPY --from=build /app/dist /dist
