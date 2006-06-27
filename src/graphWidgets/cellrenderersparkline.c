/* eggcellrenderersparkline.c
 * Copyright (C) 2005  Red Hat, Inc.,  David Malcolm <dmalcolm@redhat.com>
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

#include <stdlib.h>
#include "cellrenderersparkline.h"

static void gtk_cell_renderer_sparkline_init(GtkCellRendererSparkline *cellsparkline);
static void gtk_cell_renderer_sparkline_class_init(GtkCellRendererSparklineClass *class);
static void gtk_cell_renderer_sparkline_finalize(GObject *object);

static void gtk_cell_renderer_sparkline_get_property(GObject *object,
						     guint param_id,
						     GValue *value,
						     GParamSpec *pspec);
static void gtk_cell_renderer_sparkline_set_property(GObject *object,
						     guint param_id,
						     const GValue *value,
						     GParamSpec *pspec);
static void gtk_cell_renderer_sparkline_get_size(GtkCellRenderer *cell,
						 GtkWidget *widget,
						 GdkRectangle *cell_area,
						 gint *x_offset,
						 gint *y_offset,
						 gint *width,
						 gint *height);
static void gtk_cell_renderer_sparkline_render(GtkCellRenderer *cell,
					       GdkWindow *window,
					       GtkWidget *widget,
					       GdkRectangle *background_area,
					       GdkRectangle *cell_area,
					       GdkRectangle *expose_area,
					       GtkCellRendererState flags);

enum {
  EDITED,
  LAST_SIGNAL
};

enum {
  PROP_0,
  PROP_NUMDATAPOINTS,
  PROP_DATAARRAY
};

static gpointer parent_class;
static guint sparkline_cell_renderer_signals [LAST_SIGNAL];

#define GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE(obj) (G_TYPE_INSTANCE_GET_PRIVATE ((obj), GTK_TYPE_CELL_RENDERER_SPARKLINE, GtkCellRendererSparklinePrivate))

typedef struct _GtkCellRendererSparklinePrivate GtkCellRendererSparklinePrivate;
struct _GtkCellRendererSparklinePrivate
{
  gboolean filled;
  GValueArray *data_array;
};


GType gtk_cell_renderer_sparkline_get_type (void)
{
  static GType cell_sparkline_type = 0;

  if (!cell_sparkline_type) {
    static const GTypeInfo cell_sparkline_info = {
      sizeof (GtkCellRendererSparklineClass),
      NULL,		/* base_init */
      NULL,		/* base_finalize */
      (GClassInitFunc) gtk_cell_renderer_sparkline_class_init,
      NULL,		/* class_finalize */
      NULL,		/* class_data */
      sizeof (GtkCellRendererSparkline),
      0,              /* n_preallocs */
      (GInstanceInitFunc) gtk_cell_renderer_sparkline_init,
    };

    cell_sparkline_type =
      g_type_register_static (GTK_TYPE_CELL_RENDERER, "GtkCellRendererSparkline",
			      &cell_sparkline_info, 0);
  }

  return cell_sparkline_type;
}

static void gtk_cell_renderer_sparkline_init (GtkCellRendererSparkline *cellsparkline)
{
  GtkCellRendererSparklinePrivate *priv;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (cellsparkline);

  priv->filled = TRUE;
  priv->filled = FALSE;
  priv->data_array = g_value_array_new(0);
}

static void gtk_cell_renderer_sparkline_class_init (GtkCellRendererSparklineClass *class)
{
  GObjectClass *object_class = G_OBJECT_CLASS (class);
  GtkCellRendererClass *cell_class = GTK_CELL_RENDERER_CLASS (class);

  parent_class = g_type_class_peek_parent (class);

  object_class->finalize = gtk_cell_renderer_sparkline_finalize;

  object_class->get_property = gtk_cell_renderer_sparkline_get_property;
  object_class->set_property = gtk_cell_renderer_sparkline_set_property;

  cell_class->get_size = gtk_cell_renderer_sparkline_get_size;
  cell_class->render = gtk_cell_renderer_sparkline_render;

  g_object_class_install_property (object_class,
				   PROP_DATAARRAY,
				   g_param_spec_value_array ("data_array",
							     "Data array",
							     "GValueArray of data",
							     g_param_spec_double("data_array_value",
										 "Data array value",
										 "GValueArray element",
										 0.0,
										 100.0,
										 0,
										 G_PARAM_READABLE | G_PARAM_WRITABLE),
							     G_PARAM_READABLE | G_PARAM_WRITABLE));

  g_type_class_add_private (object_class, sizeof (GtkCellRendererSparklinePrivate));
}

static void gtk_cell_renderer_sparkline_finalize (GObject *object)
{
  GtkCellRendererSparkline *cellsparkline = GTK_CELL_RENDERER_SPARKLINE (object);
  GtkCellRendererSparklinePrivate *priv;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (object);


  (* G_OBJECT_CLASS (parent_class)->finalize) (object);
}

static void gtk_cell_renderer_sparkline_get_property (GObject *object,
						      guint param_id,
						      GValue *value,
						      GParamSpec *pspec)
{
  GtkCellRendererSparkline *cellsparkline = GTK_CELL_RENDERER_SPARKLINE (object);
  GtkCellRendererSparklinePrivate *priv;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (object);

  switch (param_id)
    {
    case PROP_DATAARRAY:
      g_value_set_boxed(value, priv->data_array);
      break;

    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, param_id, pspec);
      break;
    }
}

static void
gtk_cell_renderer_sparkline_set_property (GObject      *object,
					  guint         param_id,
					  const GValue *value,
					  GParamSpec   *pspec)
{
  GtkCellRendererSparkline *cellsparkline = GTK_CELL_RENDERER_SPARKLINE (object);
  GtkCellRendererSparklinePrivate *priv;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (object);

  switch (param_id)
    {
    case PROP_DATAARRAY:
      g_value_array_free(priv->data_array);
      priv->data_array = g_value_array_copy(g_value_get_boxed(value));
      break;

    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, param_id, pspec);
      break;
    }
}

static void gtk_cell_renderer_sparkline_get_size (GtkCellRenderer *cell,
						  GtkWidget *widget,
						  GdkRectangle *cell_area,
						  gint *x_offset,
						  gint *y_offset,
						  gint *width,
						  gint *height)
{
  GtkCellRendererSparkline *cellsparkline = (GtkCellRendererSparkline *) cell;
  GtkCellRendererSparklinePrivate *priv;
  GValueArray *data;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (cell);

  data = priv->data_array;

  if (width)
    *width = data->n_values;

  if (height)
    *height = 20;

  if (cell_area) {
    if (x_offset) {
      *x_offset = 0;
    }
    if (y_offset) {
      *y_offset = 0;
    }
  }
}

static double get_x (double right_margin_x,
		     double data_points_per_pixel,
		     int index,
		     int num_data_points)
{
  return right_margin_x - ((double)(num_data_points-(index+1))/data_points_per_pixel);
}

static double get_y (GdkRectangle *cell_area,
		     GValueArray *data,
		     int index)
{
  double baseline_y = cell_area->y + cell_area->height;
  GValue *val = g_value_array_get_nth(data, index);
  return baseline_y - (cell_area->height * g_value_get_double(val));
}

static void
gtk_cell_renderer_sparkline_render (GtkCellRenderer *cell,
				    GdkDrawable *window,
				    GtkWidget *widget,
				    GdkRectangle *background_area,
				    GdkRectangle *cell_area,
				    GdkRectangle *expose_area,
				    GtkCellRendererState flags)
{
  cairo_t *cr;
  int index;
  double right_margin_x;
  double margin = 2.0;
  double dot_radius = 1.0;
  double data_points_per_pixel = 1.0;
  double baseline_y = cell_area->y + cell_area->height;

  GtkCellRendererSparklinePrivate *priv;
  GValueArray *data;

  priv = GTK_CELL_RENDERER_SPARKLINE_GET_PRIVATE (cell);

  data = priv->data_array;

  /*
  printf ("sparkline_render\n");
  printf ("background_area=(%d,%d,%d,%d)\n", background_area->x, background_area->y, background_area->width, background_area->height);
  printf ("cell_area=(%d,%d,%d,%d)\n", cell_area->x, cell_area->y, cell_area->width, cell_area->height);
  printf ("expose_area=(%d,%d,%d,%d)\n", expose_area->x, expose_area->y, expose_area->width, expose_area->height);
  */

  cr = gdk_cairo_create (window);

  /* Clip to the cell: */
  cairo_save (cr);
  cairo_rectangle (cr, cell_area->x, cell_area->y, cell_area->width, cell_area->height);
  cairo_clip (cr);

  right_margin_x = cell_area->x + cell_area->width - margin;

  /* Render the line: */
  //cairo_set_line_width (cr, (double)cell_area->width*0.5/(double)NUM_VALUES);
  cairo_set_line_width (cr, (double)0.5);

  for (index=0;index<data->n_values;index++) {
    double cx = get_x (right_margin_x, data_points_per_pixel, index, data->n_values);
    double cy = get_y (cell_area, data, index);
    if (index) {
      cairo_line_to (cr, cx, cy);
    } else {
      cairo_move_to (cr, cx, cy);
    }
  }
  if (priv->filled) {
    cairo_line_to (cr, right_margin_x, baseline_y);
    cairo_line_to (cr, get_x (right_margin_x, data_points_per_pixel, 0, data->n_values), baseline_y);
    cairo_fill (cr);
  } else {
    cairo_stroke (cr);
  }

  /* Stop clipping: */
  cairo_restore (cr);

  /* Render the dot for the last value: */
  /*
  if (data->n_values>0) {
    cairo_set_source_rgb (cr, 1., 0., 0.);
    cairo_arc (cr, right_margin_x, get_y (cell_area, data, data->n_values-1), dot_radius, 0., 2 * 3.14159265359);
    cairo_fill (cr);
  }
  */

  cairo_destroy (cr);
}

#define __GTK_CELL_RENDERER_SPARKLINE_C__
