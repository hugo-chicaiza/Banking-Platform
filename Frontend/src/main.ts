import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { App } from './app/app';

bootstrapApplication(App, appConfig).catch((error: unknown) => {
  // Única excepción permitida a `no-console` en el frontend: si el arranque
  // falla no hay aplicación, ni logger, ni pantalla donde mostrar nada. Sin
  // esta traza el navegador quedaría en blanco sin explicación.
  // eslint-disable-next-line no-console
  console.error('[bootstrap] la aplicación no pudo arrancar', error);
});
