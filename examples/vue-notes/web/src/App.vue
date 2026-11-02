<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

import { CakeUIError, emit, invoke, listen } from "./lib/cakeui/cakeui.js";

interface Note {
  id: number;
  text: string;
  done: boolean;
  created_at: string;
}

interface AppInfo {
  python: string;
  platform: string;
  cakeui: string;
  notes_file: string;
  max_text: number;
}

interface Failure {
  code: string;
  message: string;
  details?: unknown;
}

const notes = ref<Note[]>([]);
const draft = ref("");
const failure = ref<Failure | null>(null);
const info = ref<AppInfo | null>(null);
const pending = ref(false);
const synced = ref("");
const maxText = ref(140);

const doneCount = computed(() => notes.value.filter((note) => note.done).length);
const openCount = computed(() => notes.value.length - doneCount.value);
const draftLength = computed(() => draft.value.trim().length);
const tooLong = computed(() => draftLength.value > maxText.value);
const canAdd = computed(() => draftLength.value > 0 && !tooLong.value);

/** Turn anything thrown by the bridge into the shape the banner renders. */
function describe(error: unknown): Failure {
  if (error instanceof CakeUIError) {
    return { code: error.code, message: error.message, details: error.details };
  }
  return {
    code: "unknown",
    message: error instanceof Error ? error.message : String(error),
  };
}

/**
 * Every call goes through here: Python errors become banner state instead of
 * unhandled rejections. `undefined` means "failed, already reported".
 */
async function call<T>(action: () => Promise<T>): Promise<T | undefined> {
  pending.value = true;
  try {
    const result = await action();
    return result;
  } catch (error) {
    failure.value = describe(error);
    return undefined;
  } finally {
    pending.value = false;
  }
}

async function load(): Promise<void> {
  const loaded = await call(() => invoke<Note[]>("list_notes"));
  if (loaded !== undefined) {
    notes.value = loaded;
    synced.value = `${loaded.length} note${loaded.length === 1 ? "" : "s"}`;
  }
}

async function add(): Promise<void> {
  if (!canAdd.value) {
    return;
  }
  failure.value = null;
  const updated = await call(() => invoke<Note[]>("add_note", { text: draft.value }));
  if (updated !== undefined) {
    notes.value = updated;
    draft.value = "";
  }
}

async function toggle(note: Note): Promise<void> {
  // The whole note goes back, not just the id: Python re-validates it against
  // the same Pydantic model and saves whatever it is handed.
  const updated = await call(() =>
    invoke<Note[]>("save_note", { note: { ...note, done: !note.done } }),
  );
  if (updated !== undefined) {
    notes.value = updated;
  }
}

async function remove(note: Note): Promise<void> {
  const updated = await call(() => invoke<Note[]>("delete_note", { note_id: note.id }));
  if (updated !== undefined) {
    notes.value = updated;
  }
}

async function clearDone(): Promise<void> {
  const updated = await call(() => invoke<Note[]>("clear_done"));
  if (updated !== undefined) {
    notes.value = updated;
  }
}

/** Ask Python to fail, so the error banner is not just theoretical. */
async function provoke(): Promise<void> {
  await call(() => invoke("crash", { kind: "example" }));
}

/** JS -> Python event; `on_log` in main.py prints this to the terminal. */
async function log(): Promise<void> {
  await call(() =>
    emit("log", { message: `clicked the log button with ${notes.value.length} notes` }),
  );
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

let stopListening: (() => void) | undefined;

onMounted(async () => {
  const facts = await call(() => invoke<AppInfo>("app_info"));
  if (facts) {
    info.value = facts;
    maxText.value = facts.max_text;
  }

  // Python -> JS. The event is a nudge, not the data: it says something changed,
  // so re-read through `list_notes`. That is what keeps a second window honest,
  // including the toggles that leave the count alone.
  stopListening = listen("notes:changed", () => {
    void load();
  });

  await load();
});

onUnmounted(() => stopListening?.());
</script>

<template>
  <main class="app">
    <header class="bar">
      <div>
        <h1>Vue Notes</h1>
        <p class="tagline">A Vue 3 frontend, a Python backend, one bridge.</p>
      </div>
      <div class="counts" :title="synced">
        <span class="pill">{{ openCount }} open</span>
        <span class="pill muted">{{ doneCount }} done</span>
      </div>
    </header>

    <form class="composer" @submit.prevent="add">
      <input
        v-model="draft"
        type="text"
        placeholder="What needs remembering?"
        autocomplete="off"
        :disabled="pending && !draft"
        aria-label="New note"
      />
      <button type="submit" :disabled="!canAdd || pending">Add</button>
    </form>
    <p class="meter" :class="{ over: tooLong }">
      {{ draftLength }} / {{ maxText }}
      <span v-if="tooLong">· too long, Python will refuse it</span>
    </p>

    <p v-if="failure" class="failure" role="alert">
      <strong>{{ failure.code }}</strong>
      <span>{{ failure.message }}</span>
      <button type="button" class="dismiss" @click="failure = null" aria-label="Dismiss">
        &times;
      </button>
    </p>

    <ul v-if="notes.length" class="notes">
      <li v-for="note in notes" :key="note.id" :class="{ done: note.done }">
        <label class="check">
          <input
            type="checkbox"
            :checked="note.done"
            :disabled="pending"
            @change="toggle(note)"
          />
          <span class="mark" aria-hidden="true"></span>
        </label>

        <div class="body">
          <p class="text">{{ note.text }}</p>
          <p class="meta">#{{ note.id }} · {{ formatDate(note.created_at) }}</p>
        </div>

        <button
          type="button"
          class="remove"
          :disabled="pending"
          :aria-label="`Delete note ${note.id}`"
          @click="remove(note)"
        >
          Delete
        </button>
      </li>
    </ul>

    <p v-else class="empty">
      Nothing here yet. Add your first note above; it is stored in
      <code>notes.json</code> on the Python side.
    </p>

    <footer class="footer">
      <p v-if="info" class="facts">
        Python {{ info.python }} · {{ info.platform }} · cakeui {{ info.cakeui }}
      </p>
      <p v-else class="facts">Waiting for the Python bridge...</p>

      <div class="actions">
        <button type="button" class="ghost" :disabled="!doneCount || pending" @click="clearDone">
          Clear done
        </button>
        <button type="button" class="ghost" :disabled="pending" @click="log">
          Log to Python
        </button>
        <button type="button" class="ghost danger" :disabled="pending" @click="provoke">
          Break something
        </button>
      </div>
    </footer>
  </main>
</template>
