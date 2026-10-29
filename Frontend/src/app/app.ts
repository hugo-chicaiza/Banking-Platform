import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { environment } from '../environments/environment';

/**
 * Componente raíz de la aplicación.
 *
 * Es deliberadamente mínimo: F-02 solo monta el proyecto. El layout con menú
 * lateral y el ruteo protegido por rol son alcance de F-05 (#21).
 */
@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  protected readonly title = signal('Banking Platform');

  /** Se muestra en pantalla para distinguir a simple vista dev / staging / producción. */
  protected readonly environmentName = environment.name;

  protected readonly apiBaseUrl = environment.apiBaseUrl;
}
