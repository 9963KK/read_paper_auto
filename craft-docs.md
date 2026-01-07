# Craft – API for 所有文档的 API

**Version:** 1.0.0

## Overview
The Craft Space API provides programmatic access to your entire Craft space - the top-level container for all your documents and organizational structure.

## Space Structure
A Craft space organizes content through:
- **Folders**: Hierarchical folders to organize documents
- **Documents**: Individual documents within locations
- **Blocks**: The content within documents (text, pages, collections, media)
- **Tasks**: Task management across inbox, daily notes, and documents

## Key Concepts
**Locations**: Documents exist in locations. A location is either a folder or one of the built-in locations: 'unsorted' (default for new documents), 'templates', or 'trash' (recently deleted).

**Document IDs**: A document ID is the same as its root block ID. Use a document ID with `GET /blocks` to fetch the document's content.

**Space Discovery**: Use `GET /folders` to see all locations, then `GET /documents` to list documents within a specific location.

**Document Organization**: Documents can be created in, moved between, and deleted from locations. Use folder and document management endpoints to organize your space.

**Tasks**: Tasks can be managed across the space. Use `GET /tasks` with scope filters (inbox, active, upcoming, logbook) to retrieve tasks, and other task endpoints to create, update, or delete them.

## Development Tips
- Start with `GET /folders` to discover all locations in the space
- Use `GET /documents` with a location filter to list documents in a specific location
- Create new locations with `POST /folders`
- Use `POST /documents` to create new documents in a specific location
- Access document content with `GET /blocks?id={documentId}`
- Search across the entire space with `GET /documents/search`
- Use `PUT /documents/move` to move documents between locations
- Manage tasks with `GET /tasks?scope=active` to retrieve due tasks, or use other scopes (inbox, upcoming, logbook)

## Note for AI
When implementing functionality using this API, always make actual calls to these endpoints and verify the responses. Do not simulate or mock the API interactions or use hard-coded values on the client-side - use the real endpoints to ensure proper functionality and data handling.

**IMPORTANT: This is a production server connected to real user data.** Only perform testing operations that can be safely rolled back:

- Safe: Reading data (`GET` requests), creating test content that you delete immediately after
- Safe: Modifying content if you can restore it to its original state
- Safe: Moving blocks if you can move them back to their original position
- Unsafe: Permanent deletions, modifications without backup, or any changes you cannot reverse

Always verify rollback operations work before considering a test complete.

## Servers

- https://connect.craft.do/links/<YOUR_CRAFT_LINK_ID>/api/v1
  API Server for 所有文档的 API

---

# Endpoints

# Fetch Blocks

`GET /blocks`

Fetches content from any document in the space. Use 'id' query parameter to specify which block to fetch.

Use `Accept` header `application/json` for structured data, `text/markdown` for rendered content.

**Content Rendering:** Text blocks contain markdown formatting and markdown formatted output may include structural tags like `<page></page>`, etc. When displaying content, consider rendering markdown as formatted text or cleaning up the syntax for plain text display.

**Full Space Access:** This connection has access to all documents across all locations in the space. Block links and relations within the space are preserved.

**Tip:** Start with GET /folders to see all locations, then GET /documents to list documents by location. Use document IDs as the 'id' parameter to fetch content.

## Parameters

- **date** (query): string
  Fetches the root page of a Daily Note for the specified date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
Mutually exclusive with 'id' - use this to fetch a Daily Note's root page, or use 'id' to fetch a specific block.
- **id** (required) (query): string
  Fetches a specific page block by its ID. Use this when you want to retrieve a particular block directly.
Mutually exclusive with 'date' - omit 'date' entirely when using this parameter.
- **maxDepth** (query): number
  The maximum depth of blocks to fetch. Default is -1 (all descendants). With a depth of 0, only the specified block is fetched. With a depth of 1, only direct children are returned.
- **fetchMetadata** (query): boolean
  Whether to fetch metadata (comments, createdBy, lastModifiedBy, lastModifiedAt, createdAt) for the blocks. Default is false.

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`

```json
{
  "id": "0",
  "type": "page",
  "textStyle": "page",
  "markdown": "<page>Document Title</page>",
  "content": [
    {
      "id": "1",
      "type": "text",
      "textStyle": "h1",
      "markdown": "# Main Section"
    },
    {
      "id": "2",
      "type": "text",
      "markdown": "This is some content in the document."
    },
    {
      "id": "3",
      "type": "page",
      "textStyle": "card",
      "markdown": "Subsection",
      "content": [
        {
          "id": "4",
          "type": "text",
          "markdown": "Nested content inside subsection."
        }
      ]
    }
  ]
}
```

---

# Insert Blocks

`POST /blocks`

Insert content into any document in the space. Content can be provided as structured JSON blocks. Use position parameter to specify where to insert (via parent blockId or sibling blockId). Returns the inserted blocks with their assigned block IDs for later reference.

## Request Body

**Content-Type:** `application/json`


**Example: textBlock**

Insert block into document

```json
{
  "blocks": [
    {
      "type": "text",
      "markdown": "## Section Header\n\nContent."
    }
  ],
  "position": {
    "position": "end",
    "pageId": "doc-123"
  }
}
```


**Example: markdown**

Insert markdown into daily note

```json
{
  "markdown": "## Meeting Notes\n\nDiscussed topics",
  "position": {
    "position": "end",
    "date": "today"
  }
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "15",
      "type": "text",
      "textStyle": "body",
      "markdown": "## Second Level Header\n\n- **List Item A**: Description text\n- **List Item B**: Description text"
    },
    {
      "id": "16",
      "type": "image",
      "url": "https://res.luki.io/user/full/space-id/doc/doc-id/uuid",
      "altText": "Alt text for accessibility",
      "markdown": "![Image](https://res.luki.io/user/full/space-id/doc/doc-id/uuid)"
    }
  ]
}
```

---

# Delete Blocks

`DELETE /blocks`

Delete content from any document in the space. Removes specified blocks by their IDs.

## Request Body

**Content-Type:** `application/json`

```json
{
  "blockIds": [
    "7",
    "9",
    "12"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "7"
    },
    {
      "id": "9"
    },
    {
      "id": "12"
    }
  ]
}
```

---

# Update Blocks

`PUT /blocks`

Update content in any document in the space. For text blocks, provide updated markdown content. Only the fields that are provided will be updated.

## Request Body

**Content-Type:** `application/json`

```json
{
  "blocks": [
    {
      "id": "5",
      "markdown": "## Updated Section Title\n\nThis content has been updated with new information.",
      "font": "serif"
    },
    {
      "id": "8",
      "markdown": "# New Heading"
    }
  ]
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "5",
      "type": "text",
      "textStyle": "body",
      "markdown": "## Updated Section Title\n\nThis content has been updated with new information.",
      "font": "serif"
    },
    {
      "id": "8",
      "type": "text",
      "textStyle": "h2",
      "markdown": "# New Heading"
    }
  ]
}
```

---

# Move Blocks

`PUT /blocks/move`

Move blocks to reorder them or move them between any documents across all locations in the space. Returns the moved block IDs.

## Request Body

**Content-Type:** `application/json`


**Example: moveToDoc**

Move blocks to document

```json
{
  "blockIds": [
    "5",
    "6"
  ],
  "position": {
    "position": "end",
    "pageId": "doc-123"
  }
}
```


**Example: moveToDailyNote**

Move blocks to daily note

```json
{
  "blockIds": [
    "7",
    "8"
  ],
  "position": {
    "position": "end",
    "date": "today"
  }
}
```

## Responses

### 200
Successfully moved resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "5"
    },
    {
      "id": "6"
    }
  ]
}
```

---

# Search in Document

`GET /blocks/search`

Search within a single document. Use documents_search first to find documents, then this tool for more context with before/after blocks.

## Parameters

- **blockId** (required) (query): string
  The block ID (document or page) to search within.
- **pattern** (required) (query): string
  The search patterns to look for. Patterns must follow RE2-compatible syntax, which supports most common regular-expression features (literal text, character classes, grouping alternation, quantifiers, lookaheads, and fixed-width lookbehinds.
- **caseSensitive** (query): boolean
  Whether the search should be case sensitive. Default is false.
- **beforeBlockCount** (query): number
  The number of blocks to include before the matched block.
- **afterBlockCount** (query): number
  The number of blocks to include after the matched block.

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`


**Example: withContext**

Search for 'Description' with context blocks

```json
{
  "items": [
    {
      "blockId": "109",
      "markdown": "List Item A: Description text",
      "pageBlockPath": [
        {
          "id": "0",
          "content": "Document Title"
        }
      ],
      "beforeBlocks": [
        {
          "blockId": "108",
          "markdown": "## Second Level Header"
        }
      ],
      "afterBlocks": [
        {
          "blockId": "110",
          "markdown": "List Item B: Description text"
        },
        {
          "blockId": "111",
          "markdown": "List Item C: Description text"
        }
      ]
    }
  ]
}
```

**Example: deeplyNested**

Search in deeply nested structure

```json
{
  "items": [
    {
      "blockId": "15",
      "markdown": "Match found here",
      "pageBlockPath": [
        {
          "id": "0",
          "content": "Document Title"
        },
        {
          "id": "12",
          "content": "Section Card"
        },
        {
          "id": "14",
          "content": "Nested Card"
        }
      ],
      "beforeBlocks": [
        {
          "blockId": "13",
          "markdown": "Previous content"
        }
      ],
      "afterBlocks": [
        {
          "blockId": "16",
          "markdown": "Following content"
        }
      ]
    }
  ]
}
```

---

# Search across Documents

`GET /documents/search`

Search content across all documents in the space using relevance-based ranking. Supports flat date filter fields (createdDateGte, createdDateLte, lastModifiedDateGte, lastModifiedDateLte, dailyNoteDateGte, dailyNoteDateLte) for time-based queries and location object for filtering by folder.

- Searches the entire space (all locations)
- Relevance-based ranking (top 20 results)
- Content snippets with match highlighting
- Filter by date ranges or location

**Example Use Cases:**
- Find all mentions of a topic anywhere in the space
- Search for specific content across all documents
- Search documents within a specific location or folder

## Parameters

- **include** (query): string
  Search terms to include in the search. Can be a single string or array of strings.
- **regexps** (query): string
  Search terms to include in the search. Patterns must follow RE2-compatible syntax, which supports most common regular-expression features (literal text, character classes, grouping alternation, quantifiers, lookaheads, and fixed-width lookbehinds.
- **documentIds** (query): string
  The document IDs to filter. Cannot be used together with 'location' or 'folderIds'. If not provided, all documents will be searched. Can be a single string or array of strings.
- **fetchMetadata** (query): boolean
  Whether to include document metadata (lastModifiedAt, createdAt) in each search result. Default is false.
- **location** (query): string
  Filter by virtual location: 'unsorted', 'trash', 'templates', or 'daily_notes'. Cannot be used together with 'folderId' or 'documentIds'. If neither 'location' nor 'folderId' is specified, searches/lists all documents.
- **folderIds** (query): string
  Filter by specific folders (includes subfolders recursively). Cannot be used together with 'location' or 'documentIds'. If neither 'location' nor 'folderIds' is specified, searches all documents. Can be a single string or array of strings.
- **createdDateGte** (query): string
  Only include documents created on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **createdDateLte** (query): string
  Only include documents created on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **lastModifiedDateGte** (query): string
  Only include documents modified on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **lastModifiedDateLte** (query): string
  Only include documents modified on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **dailyNoteDateGte** (query): string
  Only include daily notes on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **dailyNoteDateLte** (query): string
  Only include daily notes on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`


**Example: basicSearch**

Search for 'API' across all documents

```json
{
  "items": [
    {
      "documentId": "doc-123",
      "markdown": "The **API** endpoints are documented..."
    },
    {
      "documentId": "doc-456",
      "markdown": "**API** authentication requires..."
    }
  ]
}
```

**Example: filteredSearch**

Search with document filtering

```json
{
  "items": [
    {
      "documentId": "doc-123",
      "markdown": "Authentication **token** is required..."
    }
  ]
}
```

---

# List Collections

`GET /collections`

List all collections across the entire space. Returns collections from all documents regardless of their location.

## Parameters

- **documentIds** (query): string
  The document IDs to filter. If not provided, collections in all documents will be listed. Can be a single string or array of strings.

## Responses

### 200
Success

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "col1",
      "name": "Tasks",
      "itemCount": 5,
      "documentId": "doc1"
    },
    {
      "id": "col2",
      "name": "Notes",
      "itemCount": 3,
      "documentId": "doc2"
    }
  ]
}
```

---

# List Documents

`GET /documents`

List documents in the space. Without location or folderIds filters, returns ALL documents (may be large). Recommended: use GET /folders first to see available locations and document counts.

## Parameters

- **location** (query): string
  Filter by virtual location: 'unsorted', 'trash', 'templates', or 'daily_notes'. Cannot be used together with 'folderId' or 'documentIds'. If neither 'location' nor 'folderId' is specified, searches/lists all documents.
- **folderId** (query): string
  Filter by specific folder (includes subfolders recursively). Cannot be used together with 'location' or 'documentIds'. If neither 'location' nor 'folderId' is specified, lists all documents.
- **fetchMetadata** (query): boolean
  Whether to include metadata (lastModifiedAt, createdAt) in the response. Default is false.
- **createdDateGte** (query): string
  Only include documents created on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **createdDateLte** (query): string
  Only include documents created on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **lastModifiedDateGte** (query): string
  Only include documents modified on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **lastModifiedDateLte** (query): string
  Only include documents modified on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **dailyNoteDateGte** (query): string
  Only include daily notes on or after this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.
- **dailyNoteDateLte** (query): string
  Only include daily notes on or before this date. Accepts ISO format YYYY-MM-DD or relative dates: 'today', 'tomorrow', 'yesterday'.

## Responses

### 200
Success

**Content-Type:** `application/json`


**Example: unsorted**

Documents in unsorted

```json
{
  "items": [
    {
      "id": "doc-123",
      "title": "Meeting Notes"
    },
    {
      "id": "doc-456",
      "title": "Project Ideas"
    }
  ]
}
```

**Example: dailyNotes**

Daily notes with dates

```json
{
  "items": [
    {
      "id": "dn-123",
      "title": "Wednesday, January 15, 2025",
      "dailyNoteDate": "2025-01-15"
    },
    {
      "id": "dn-456",
      "title": "Tuesday, January 14, 2025",
      "dailyNoteDate": "2025-01-14"
    }
  ]
}
```

**Example: withMetadata**

Documents with metadata

```json
{
  "items": [
    {
      "id": "doc-123",
      "title": "Meeting Notes",
      "lastModifiedAt": "2025-01-15T14:30:00Z",
      "createdAt": "2025-01-10T09:00:00Z",
      "clickableLink": "craftdocs://open?spaceId=space-uuid&documentId=doc-uuid-123"
    }
  ]
}
```

---

# Create Documents

`POST /documents`

Create one or more documents in the space. Specify location as 'unsorted' (default), 'templates', or provide a folderId. Cannot create in 'trash'.

## Request Body

**Content-Type:** `application/json`


**Example: unsorted**

Create documents in unsorted

```json
{
  "documents": [
    {
      "title": "New Document 1"
    },
    {
      "title": "New Document 2"
    }
  ]
}
```


**Example: folder**

Create documents in a folder

```json
{
  "documents": [
    {
      "title": "Project Plan"
    }
  ],
  "destination": {
    "folderId": "abc123"
  }
}
```


**Example: templates**

Create template documents

```json
{
  "documents": [
    {
      "title": "Weekly Report Template"
    }
  ],
  "destination": {
    "destination": "templates"
  }
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "doc-new-1",
      "title": "New Document 1"
    },
    {
      "id": "doc-new-2",
      "title": "New Document 2"
    }
  ]
}
```

---

# Delete Documents

`DELETE /documents`

Soft-delete documents by moving them to trash. Use documents_move to restore.

## Request Body

**Content-Type:** `application/json`

```json
{
  "documentIds": [
    "doc-123",
    "doc-456"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    "doc-123",
    "doc-456"
  ]
}
```

---

# Move Documents

`PUT /documents/move`

Move documents between locations in the space. Destination cannot be 'trash' - use documents_delete instead. Use this to restore documents from trash. Note: Daily notes cannot be moved.

## Request Body

**Content-Type:** `application/json`


**Example: toFolder**

Move documents to a folder

```json
{
  "documentIds": [
    "doc-123",
    "doc-456"
  ],
  "destination": {
    "folderId": "abc123"
  }
}
```


**Example: toUnsorted**

Move documents to unsorted

```json
{
  "documentIds": [
    "doc-789"
  ],
  "destination": {
    "destination": "unsorted"
  }
}
```


**Example: restoreFromTrash**

Restore documents from trash

```json
{
  "documentIds": [
    "doc-deleted"
  ],
  "destination": {
    "destination": "unsorted"
  }
}
```

## Responses

### 200
Successfully moved resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "doc-123",
      "destination": {
        "folderId": "abc123"
      }
    },
    {
      "id": "doc-456",
      "destination": {
        "folderId": "abc123"
      }
    }
  ]
}
```

---

# List Folders

`GET /folders`

Get all locations in the space with document counts. Returns built-in locations (Unsorted, Trash, Templates) and user-created folders with their hierarchical structure.

## Responses

### 200
Success

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "unsorted",
      "name": "Unsorted",
      "documentCount": 42,
      "folders": []
    },
    {
      "id": "trash",
      "name": "Recently Deleted",
      "documentCount": 3,
      "folders": []
    },
    {
      "id": "templates",
      "name": "Templates",
      "documentCount": 5,
      "folders": []
    },
    {
      "id": "abc123",
      "name": "Projects",
      "documentCount": 10,
      "folders": [
        {
          "id": "def456",
          "name": "Work",
          "documentCount": 5,
          "folders": []
        }
      ]
    }
  ]
}
```

---

# Create Folders

`POST /folders`

Create one or more folders. Supports creating at root level or nested inside existing folders. Cannot create inside built-in locations.

## Request Body

**Content-Type:** `application/json`


**Example: createRootFolder**

Create folder at root level

```json
{
  "folders": [
    {
      "name": "New Project"
    }
  ]
}
```


**Example: createNestedFolder**

Create nested folder inside another folder

```json
{
  "folders": [
    {
      "name": "Subproject",
      "parentFolderId": "abc123"
    }
  ]
}
```


**Example: createMultipleFolders**

Create multiple folders at once

```json
{
  "folders": [
    {
      "name": "Marketing"
    },
    {
      "name": "Engineering"
    },
    {
      "name": "Q1 Planning",
      "parentFolderId": "abc123"
    }
  ]
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "xyz789",
      "name": "New Project"
    },
    {
      "id": "mno345",
      "name": "Subproject",
      "parentFolderId": "abc123"
    }
  ]
}
```

---

# Delete Folders

`DELETE /folders`

Delete folders. Documents and subfolders are moved to the parent folder, or Unsorted if deleting a top-level folder. Cannot delete built-in locations.

## Request Body

**Content-Type:** `application/json`

```json
{
  "folderIds": [
    "abc123",
    "def456"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    "abc123",
    "def456"
  ]
}
```

---

# Move Folders

`PUT /folders/move`

Move folders within the hierarchy. Supports moving to root or inside another folder. Cannot move built-in locations.

## Request Body

**Content-Type:** `application/json`


**Example: moveToRoot**

Move folders to root level

```json
{
  "folderIds": [
    "abc123"
  ],
  "destination": "root"
}
```


**Example: moveToParent**

Move folders inside another folder

```json
{
  "folderIds": [
    "abc123",
    "def456"
  ],
  "destination": {
    "parentFolderId": "xyz789"
  }
}
```

## Responses

### 200
Successfully moved resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "abc123",
      "destination": "root"
    },
    {
      "id": "def456",
      "destination": {
        "parentFolderId": "xyz789"
      }
    }
  ]
}
```

---

# Get Collection Schema

`GET /collections/{collectionId}/schema`

Get collection schema in JSON Schema format

## Parameters

- **format** (query): string
  The format to return the schema in. Default: json-schema-items. - 'schema': Returns the collection schema structure that can be edited - 'json-schema-items': Returns JSON Schema for addCollectionItems/updateCollectionItems validation
- **collectionId** (required) (path): string

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`


**Example: schemaFormat**

Schema format response

```json
{
  "key": "tasks",
  "name": "Tasks",
  "contentPropDetails": {
    "key": "title",
    "name": "Title"
  },
  "properties": [
    {
      "key": "status",
      "name": "Status",
      "type": "select",
      "options": [
        "Not Started",
        "In Progress",
        "Completed"
      ]
    },
    {
      "key": "priority",
      "name": "Priority",
      "type": "select",
      "options": [
        "Low",
        "Medium",
        "High"
      ]
    },
    {
      "key": "dueDate",
      "name": "Due Date",
      "type": "date"
    }
  ],
  "propertyDetails": [
    {
      "key": "status",
      "name": "Status",
      "type": "select",
      "options": [
        "Not Started",
        "In Progress",
        "Completed"
      ]
    },
    {
      "key": "priority",
      "name": "Priority",
      "type": "select",
      "options": [
        "Low",
        "Medium",
        "High"
      ]
    },
    {
      "key": "dueDate",
      "name": "Due Date",
      "type": "date"
    }
  ]
}
```

**Example: jsonSchemaFormat**

JSON Schema format (for validation)

```json
{
  "type": "object",
  "properties": {
    "items": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "title": {
            "type": "string",
            "description": "The title of the collection item"
          },
          "properties": {
            "type": "object",
            "properties": {
              "status": {
                "type": "string",
                "enum": [
                  "Not Started",
                  "In Progress",
                  "Completed"
                ],
                "description": "Status"
              },
              "priority": {
                "type": "string",
                "enum": [
                  "Low",
                  "Medium",
                  "High"
                ],
                "description": "Priority"
              },
              "dueDate": {
                "type": "string",
                "description": "Due Date"
              }
            }
          }
        },
        "required": [
          "title"
        ]
      }
    }
  },
  "required": [
    "items"
  ],
  "additionalProperties": false
}
```

---

# Get Collection Items

`GET /collections/{collectionId}/items`

Get all items from a collection

## Parameters

- **maxDepth** (query): number
  The maximum depth of nested content to fetch for each collection item. Default is -1 (all descendants). With a depth of 0, only the item properties are fetched without nested content.
- **collectionId** (required) (path): string

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "item1",
      "title": "Task 1",
      "properties": {
        "status": "In Progress",
        "priority": "High",
        "assignee": "John Doe"
      },
      "content": [
        {
          "id": "1",
          "type": "text",
          "markdown": "Detailed description of the task."
        }
      ]
    },
    {
      "id": "item2",
      "title": "Task 2",
      "properties": {
        "status": "Done",
        "priority": "Low",
        "assignee": "Jane Smith"
      }
    }
  ]
}
```

---

# Add Collection Items

`POST /collections/{collectionId}/items`

Add new items to a collection. Two-way relations are synced automatically in the background - only set one side for consistency.

## Parameters

- **collectionId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "title": "Space Task",
      "properties": {
        "status": "Todo",
        "priority": "High"
      }
    }
  ]
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "item3",
      "title": "New Task",
      "properties": {
        "status": "Todo",
        "priority": "Medium"
      }
    }
  ]
}
```

---

# Delete Collection Items

`DELETE /collections/{collectionId}/items`

Delete collection items (also deletes content inside items)

## Parameters

- **collectionId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "idsToDelete": [
    "item1",
    "item2",
    "item3"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "item1"
    },
    {
      "id": "item2"
    },
    {
      "id": "item3"
    }
  ]
}
```

---

# Update Collection Items

`PUT /collections/{collectionId}/items`

Update collection items. Two-way relations are synced automatically in the background - only set one side for consistency.

## Parameters

- **collectionId** (required) (path): string

## Request Body

**Content-Type:** `application/json`

```json
{
  "itemsToUpdate": [
    {
      "id": "item1",
      "properties": {
        "status": "Done"
      }
    }
  ]
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "item1",
      "title": "Updated Task",
      "properties": {
        "status": "Done",
        "priority": "High"
      }
    }
  ]
}
```

---

# Get Tasks

`GET /tasks`

Retrieve tasks from across the space. Tasks are organized into inbox, active, upcoming, logbook, and document categories. Use scope='document' with documentId to get tasks from a specific document.

## Parameters

- **scope** (required) (query): string
  Filter tasks by scope: - 'active': Active tasks (due before now, not completed/cancelled) - 'upcoming': Upcoming tasks (scheduled after now) - 'inbox': Tasks in the task inbox - 'logbook': Tasks in the task logbook (completed/cancelled) - 'document': Tasks in a specific document (requires documentId)
- **documentId** (query): string
  Required when scope is 'document'. The ID of the document to list tasks from.

## Responses

### 200
Successfully retrieved data

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "task-1",
      "markdown": "Review project proposal",
      "taskInfo": {
        "state": "todo",
        "scheduleDate": "2025-01-15"
      }
    },
    {
      "id": "task-2",
      "markdown": "Finalize budget review",
      "taskInfo": {
        "state": "todo",
        "scheduleDate": "2025-01-16",
        "deadlineDate": "2025-01-20"
      }
    }
  ]
}
```

---

# Add Tasks

`POST /tasks`

Create new tasks in inbox, daily notes, or specific documents. Location types: 'inbox', 'dailyNote' (with date), or 'document' (with documentId). Tasks can include schedule dates and deadlines.

## Request Body

**Content-Type:** `application/json`


**Example: addToInbox**

Add task to inbox

```json
{
  "tasks": [
    {
      "markdown": "Prepare presentation slides",
      "taskInfo": {
        "scheduleDate": "tomorrow"
      },
      "location": {
        "type": "inbox"
      }
    }
  ]
}
```


**Example: addToDailyNote**

Add task to a daily note

```json
{
  "tasks": [
    {
      "markdown": "Follow up on meeting action items",
      "taskInfo": {
        "scheduleDate": "2025-01-20",
        "deadlineDate": "2025-01-22"
      },
      "location": {
        "type": "dailyNote",
        "date": "today"
      }
    }
  ]
}
```


**Example: addToDocument**

Add task to a specific document

```json
{
  "tasks": [
    {
      "markdown": "Research findings task",
      "location": {
        "type": "document",
        "documentId": "doc-456"
      }
    }
  ]
}
```

## Responses

### 200
Successfully created resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "task-new-1",
      "markdown": "Prepare presentation slides",
      "taskInfo": {
        "state": "todo",
        "scheduleDate": "2025-01-16"
      }
    }
  ]
}
```

---

# Delete Tasks

`DELETE /tasks`

Delete tasks by their IDs from any location in the space.

## Request Body

**Content-Type:** `application/json`

```json
{
  "idsToDelete": [
    "task-1",
    "task-2"
  ]
}
```

## Responses

### 200
Successfully deleted resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "task-1"
    },
    {
      "id": "task-2"
    }
  ]
}
```

---

# Update Tasks

`PUT /tasks`

Update existing tasks across the space. Can modify task content, state, schedule dates, deadlines, and location (to move tasks). Location types: 'inbox', 'dailyNote' (with date), or 'document' (with documentId). Marking inbox tasks as done/canceled moves them to logbook.

## Request Body

**Content-Type:** `application/json`


**Example: markDone**

Mark task as done

```json
{
  "tasksToUpdate": [
    {
      "id": "task-1",
      "taskInfo": {
        "state": "done"
      }
    }
  ]
}
```


**Example: updateContent**

Update task content and schedule

```json
{
  "tasksToUpdate": [
    {
      "id": "task-2",
      "markdown": "Updated task description",
      "taskInfo": {
        "scheduleDate": "2025-01-20"
      }
    }
  ]
}
```

## Responses

### 200
Successfully updated resource

**Content-Type:** `application/json`

```json
{
  "items": [
    {
      "id": "task-1",
      "taskInfo": {
        "state": "done"
      }
    }
  ]
}
```

---
