# Web

This project was generated using [Angular CLI](https://github.com/angular/angular-cli) version 21.0.4.

## Development server

To start a local development server, run:

```bash
ng serve
```

Once the server is running, open your browser and navigate to `http://localhost:4200/`. The application will automatically reload whenever you modify any of the source files.

## Static Lite client

Lite is a separate, browser-only Angular application. It does not import the installed
application's root component or backend `ApiService`.

```bash
npm run start:lite
npm run build:lite
npm run build:lite:pages
```

The production artifact is written to `dist/lite/browser`. It includes a sample-data
tour and a direct, read-only Mastodon OAuth client. Real OAuth must be served from the
same HTTPS URL registered as its callback; localhost is intended for sample-mode and
development testing.

`build:lite:pages` sets the asset and OAuth callback base to `/mimb_lite/`. Publish
the resulting `dist/lite/browser` directory from a GitHub repository named
`mimb_lite` to serve it at:

```text
https://matthewdeanmartin.github.io/mimb_lite/
```

GitHub Pages derives a project site's path from its repository name. A Pages deploy
from the `mastodon_is_my_blog` repository cannot claim the `/mimb_lite/` project path.

## Code scaffolding

Angular CLI includes powerful code scaffolding tools. To generate a new component, run:

```bash
ng generate component component-name
```

For a complete list of available schematics (such as `components`, `directives`, or `pipes`), run:

```bash
ng generate --help
```

## Building

To build the project run:

```bash
ng build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

## Running unit tests

To execute unit tests with the [Vitest](https://vitest.dev/) test runner, use the following command:

```bash
ng test
```

## Running end-to-end tests

For end-to-end (e2e) testing, run:

```bash
ng e2e
```

Angular CLI does not come with an end-to-end testing framework by default. You can choose one that suits your needs.

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.
