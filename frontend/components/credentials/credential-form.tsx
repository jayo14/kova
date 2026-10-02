"use client";

import { useState } from "react";
import type { Credential, CreateCredentialInput, UpdateCredentialInput } from "@/lib/types";
import { credentialRoleOptions } from "@/lib/types";
import { Input } from "@/components/ui/input";
import { PasswordInput } from "@/components/ui/password-input";
import { Button } from "@/components/ui/button";
import { MaterialIcon } from "@/components/shared/material-icon";

interface CredentialFormProps {
  credential?: Credential | null;
  projects?: Array<{ id: string; name: string }>;
  initialProjectId?: string;
  onSubmit: (input: CreateCredentialInput | UpdateCredentialInput) => void;
  onCancel: () => void;
  loading?: boolean;
  error?: string | null;
}

interface FormErrors {
  name?: string;
  email?: string;
  password?: string;
  projectId?: string;
}

export function CredentialForm({
  credential,
  projects = [],
  initialProjectId,
  onSubmit,
  onCancel,
  loading = false,
  error = null,
}: CredentialFormProps) {
  const [name, setName] = useState(credential?.name ?? "");
  const [email, setEmail] = useState(credential?.email ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState(credential?.role ?? "");
  const [projectId, setProjectId] = useState(
    credential?.projectId || initialProjectId || (projects.length > 0 ? projects[0].id : "")
  );
  const [showPasswordField, setShowPasswordField] = useState(!credential);
  const [errors, setErrors] = useState<FormErrors>({});

  const validate = (): boolean => {
    const errs: FormErrors = {};
    if (!name.trim()) {
      errs.name = "Enter a name.";
    }
    if (!email.trim()) {
      errs.email = "Enter an email address.";
    } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      errs.email = "Enter a valid email address.";
    }

    if (!credential && !password.trim()) {
      errs.password = "Enter the password.";
    }
    if (credential && showPasswordField && !password.trim()) {
      errs.password = "Enter the new password.";
    }

    if (projects.length > 0 && !projectId) {
      errs.projectId = "Select a project.";
    }

    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate() || loading) return;

    if (credential) {
      const input: UpdateCredentialInput = {
        name: name.trim(),
        email: email.trim(),
        projectId: projectId || undefined,
      };
      if (role) input.role = role;
      if (showPasswordField && password.trim()) {
        input.password = password;
      }
      onSubmit(input);
    } else {
      onSubmit({
        name: name.trim(),
        email: email.trim(),
        password,
        role: role || undefined,
        projectId: projectId || undefined,
      });
    }

    // Immediately clear password from local state
    setPassword("");
  };

  const handleCancel = () => {
    setPassword("");
    onCancel();
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-xl bg-destructive/10 px-3.5 py-2.5 text-body-sm text-destructive"
        >
          <MaterialIcon
            name="error"
            size={16}
            className="text-destructive shrink-0"
          />
          <p>{error}</p>
        </div>
      )}

      {/* Name */}
      <div className="space-y-1.5">
        <label htmlFor="cred-name" className="text-body-xs font-medium text-foreground">
          Name
        </label>
        <Input
          id="cred-name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Student Account"
          disabled={loading}
          aria-invalid={!!errors.name}
          aria-describedby={errors.name ? "cred-name-error" : undefined}
          required
        />
        {errors.name && (
          <p id="cred-name-error" className="text-caption text-destructive">
            {errors.name}
          </p>
        )}
      </div>

      {/* Email */}
      <div className="space-y-1.5">
        <label htmlFor="cred-email" className="text-body-xs font-medium text-foreground">
          Email / Username
        </label>
        <Input
          id="cred-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="student@testapp.com"
          disabled={loading}
          aria-invalid={!!errors.email}
          aria-describedby={errors.email ? "cred-email-error" : undefined}
          required
        />
        {errors.email && (
          <p id="cred-email-error" className="text-caption text-destructive">
            {errors.email}
          </p>
        )}
      </div>

      {/* Password */}
      {credential && !showPasswordField ? (
        <div className="space-y-1.5">
          <label className="text-body-xs font-medium text-foreground">
            Password
          </label>
          <div className="flex items-center justify-between rounded-xl border border-border/80 bg-secondary/30 px-3 py-2">
            <div className="flex items-center gap-2">
              <MaterialIcon
                name="check_circle"
                size={16}
                className="text-emerald-600 dark:text-emerald-400"
              />
              <span className="text-body-sm text-muted-foreground">
                Saved securely
              </span>
            </div>
            <button
              type="button"
              onClick={() => setShowPasswordField(true)}
              className="text-body-xs font-medium text-primary hover:underline"
            >
              Change password
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label htmlFor="cred-password" className="text-body-xs font-medium text-foreground">
              {credential ? "New password" : "Password"}
            </label>
            {credential && (
              <button
                type="button"
                onClick={() => {
                  setShowPasswordField(false);
                  setPassword("");
                }}
                className="text-caption text-muted-foreground hover:text-foreground"
              >
                Keep existing password
              </button>
            )}
          </div>
          <PasswordInput
            id="cred-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Enter password"
            disabled={loading}
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? "cred-password-error" : undefined}
            autoComplete="new-password"
          />
          {errors.password && (
            <p id="cred-password-error" className="text-caption text-destructive">
              {errors.password}
            </p>
          )}
        </div>
      )}

      {/* Project */}
      {projects.length > 0 && (
        <div className="space-y-1.5">
          <label htmlFor="cred-project" className="text-body-xs font-medium text-foreground">
            Product
          </label>
          <select
            id="cred-project"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            disabled={loading}
            className="h-9 w-full min-w-0 rounded-xl border border-input bg-card/60 px-3 py-1 text-body-sm transition-colors outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 disabled:opacity-50"
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {errors.projectId && (
            <p className="text-caption text-destructive">{errors.projectId}</p>
          )}
        </div>
      )}

      {/* Role */}
      <div className="space-y-1.5">
        <label htmlFor="cred-role" className="text-body-xs font-medium text-foreground">
          Role (optional)
        </label>
        <select
          id="cred-role"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          disabled={loading}
          className="h-9 w-full min-w-0 rounded-xl border border-input bg-card/60 px-3 py-1 text-body-sm transition-colors outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/20 disabled:opacity-50"
        >
          <option value="">No role</option>
          {credentialRoleOptions.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </div>

      <div className="flex items-center justify-end gap-2 pt-3">
        <Button
          type="button"
          variant="ghost"
          onClick={handleCancel}
          disabled={loading}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={loading} className="gap-1.5">
          {loading ? (
            <>
              <MaterialIcon
                name="progress_activity"
                size={14}
                className="animate-spin"
              />
              Saving...
            </>
          ) : (
            "Save account"
          )}
        </Button>
      </div>
    </form>
  );
}
