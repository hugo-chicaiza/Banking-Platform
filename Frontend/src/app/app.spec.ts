import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { App } from './app';
import { environment } from '../environments/environment';
import { routes } from './app.routes';

/**
 * Pruebas de la cáscara del proyecto (F-02).
 *
 * No prueban negocio —todavía no hay—; prueban que el andamiaje funciona:
 * que la aplicación arranca, que el router está provisto y que el entorno
 * activo se refleja en pantalla. Si alguna de estas falla, el problema está
 * en la configuración del proyecto, que es justo lo que F-02 debe garantizar.
 */
describe('App (cáscara del proyecto)', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
      providers: [provideRouter(routes)],
    }).compileComponents();
  });

  it('se crea sin errores', () => {
    const fixture = TestBed.createComponent(App);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('renderiza el nombre de la aplicación', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const heading = (fixture.nativeElement as HTMLElement).querySelector('h1');
    expect(heading?.textContent).toContain('Banking Platform');
  });

  it('muestra el entorno activo, para no confundir staging con producción', async () => {
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();

    const host = fixture.nativeElement as HTMLElement;
    expect(host.querySelector('[data-testid="env-name"]')?.textContent?.trim()).toBe(
      environment.name,
    );
    expect(host.querySelector('[data-testid="api-base-url"]')?.textContent?.trim()).toBe(
      environment.apiBaseUrl,
    );
  });
});

describe('Configuración de entorno', () => {
  it('nunca habilita logs de depuración en producción', async () => {
    const produccion = await import('../environments/environment.production');
    expect(produccion.environment.enableDebugLogs).toBe(false);
    expect(produccion.environment.production).toBe(true);
  });

  it('usa una ruta relativa como apiBaseUrl en los tres entornos', async () => {
    const [desarrollo, staging, produccion] = await Promise.all([
      import('../environments/environment'),
      import('../environments/environment.staging'),
      import('../environments/environment.production'),
    ]);

    for (const entorno of [desarrollo, staging, produccion]) {
      // Una URL absoluta dejaría el host del backend escrito en el bundle
      // público y obligaría a abrir CORS. Ver environment.model.ts.
      expect(entorno.environment.apiBaseUrl.startsWith('/')).toBe(true);
    }
  });

  it('acorta el tiempo de inactividad a medida que el entorno es más sensible', async () => {
    const [desarrollo, staging, produccion] = await Promise.all([
      import('../environments/environment'),
      import('../environments/environment.staging'),
      import('../environments/environment.production'),
    ]);

    expect(desarrollo.environment.sessionIdleTimeoutMinutes).toBeGreaterThan(
      staging.environment.sessionIdleTimeoutMinutes,
    );
    expect(staging.environment.sessionIdleTimeoutMinutes).toBeGreaterThan(
      produccion.environment.sessionIdleTimeoutMinutes,
    );
  });
});
