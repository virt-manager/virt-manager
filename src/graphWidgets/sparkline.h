/* sparkline.h
 * Copyright (C) 2005  Red Hat, Inc.,  David Malcolm <dmalcolm@redhat.com>
 * Copyright (C) 2006  Red Hat, Inc.,  Daniel Berrange <berrange@redhat.com>
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Library General Public
 * License as published by the Free Software Foundation; either
 * version 2 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Library General Public License for more details.
 *
 * You should have received a copy of the GNU Library General Public
 * License along with this library; if not, write to the
 * Free Software Foundation, Inc., 59 Temple Place - Suite 330,
 * Boston, MA 02111-1307, USA.
 */

#ifndef __GTK_SPARKLINE_H__
#define __GTK_SPARKLINE_H__

#include <pango/pango.h>
#include <gtk/gtkdrawingarea.h>


G_BEGIN_DECLS


#define GTK_TYPE_SPARKLINE		(gtk_sparkline_get_type ())
#define GTK_SPARKLINE(obj)		(G_TYPE_CHECK_INSTANCE_CAST ((obj), GTK_TYPE_SPARKLINE, GtkSparkline))
#define GTK_SPARKLINE_CLASS(klass)	(G_TYPE_CHECK_CLASS_CAST ((klass), GTK_TYPE_SPARKLINE, GtkSparklineClass))
#define GTK_IS_SPARKLINE(obj)		(G_TYPE_CHECK_INSTANCE_TYPE ((obj), GTK_TYPE_SPARKLINE))
#define GTK_IS_SPARKLINE_CLASS(klass)	(G_TYPE_CHECK_CLASS_TYPE ((klass), GTK_TYPE_SPARKLINE))
#define GTK_SPARKLINE_GET_CLASS(obj)   (G_TYPE_INSTANCE_GET_CLASS ((obj), GTK_TYPE_SPARKLINE, GtkSparklineClass))

typedef struct _GtkSparkline      GtkSparkline;
typedef struct _GtkSparklineClass GtkSparklineClass;

struct _GtkSparkline
{
  GtkDrawingArea parent;

  /*< private >*/
};

struct _GtkSparklineClass
{
  GtkDrawingAreaClass parent_class;

  /* Padding for future expansion */
  void (*_gtk_reserved1) (void);
  void (*_gtk_reserved2) (void);
  void (*_gtk_reserved3) (void);
  void (*_gtk_reserved4) (void);
};

GType            gtk_sparkline_get_type (void) G_GNUC_CONST;
GtkWidget        *gtk_sparkline_new      (void);

G_END_DECLS


#endif /* __GTK_SPARKLINE_H__ */
